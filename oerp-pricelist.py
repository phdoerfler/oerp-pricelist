#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

# (C) Max Gaukler, Julian Hammer 2014
# unlimited usage allowed, see LICENSE file

# Dependencies

# from lxml import etree
# import StringIO
# import math
# import urllib2
# from decimal import Decimal
# from pprint import pprint
# import os
# import inspect
from copy import deepcopy
import sys
import re
import oerplib
import locale
from ConfigParser import ConfigParser
import codecs
import cgi
import time
from repoze.lru import lru_cache
LRU_CACHE_MAX_ENTRIES=327678

import natsort


# switching to german:
locale.setlocale(locale.LC_ALL, "de_DE.UTF-8")
reload(sys).setdefaultencoding('UTF-8')  # somehow doesn't work

if sys.stdout.encoding != "UTF-8":
    print sys.stdout.encoding
    print >> sys.stderr, "please use a UTF-8 locale, e.g. LANG=en_US.UTF-8"
    exit(1)

cfg = ConfigParser({})
cfg.readfp(codecs.open('config.ini', 'r', 'utf8'))

oerp = oerplib.OERP(server=cfg.get('openerp', 'server'), protocol='xmlrpc+ssl',
                    database=cfg.get('openerp', 'database'), port=cfg.getint('openerp', 'port'),
                    version=cfg.get('openerp', 'version'))
user = oerp.login(user=cfg.get('openerp', 'user'), passwd=cfg.get('openerp', 'password'))
oerpContext = oerp.context


def str_to_int(s, fallback=None):
    try:
        return int(s)
    except ValueError:
        return fallback





@lru_cache(LRU_CACHE_MAX_ENTRIES)
def categ_id_to_list_of_names(c_id):
    # TODO make this faster by once fetching the list of all categories
    categ = get_category(c_id)

    if not categ['parent_id'] or categ['parent_id'][0] == cfg.getint('openerp', 'base_category_id'):
        return [categ['name']]
    else:
        return categ_id_to_list_of_names(categ['parent_id'][0]) + [categ['name']]


class NotFound(Exception):
    pass


def get_id(db, prod_filter):
    ids = get_ids(db, prod_filter)
    if not ids:
        raise NotFound("cannot find {} from search {}".format(db, str(prod_filter)))
    assert len(ids) == 1, "found more than one {} from search {}".format(db, str(prod_filter))
    return ids[0]


def get_ids(db, prod_filter):
    return oerp.search(db, prod_filter, context=oerpContext)


def read(db, prod_id, fields=None):
    if not fields:
        fields = []
    assert type(
        prod_id) == int, "read is only for one element. " \
                         "See also: read_elements() for reading multiple elements with a filter"
    read_result = oerp.read(db, [prod_id], fields, context=oerpContext)
    if len(read_result) != 1:
        raise NotFound()
    return read_result[0]


def write(db, prod_id, data):
    return oerp.write(db, [prod_id], data, context=oerpContext)


def create(db, data):
    return oerp.create(db, data, context=oerpContext)


def read_elements(db, element_filter, fields=None):
    if not fields:
        fields = []
    return oerp.read(db, get_ids(db, element_filter), fields, context=oerpContext)


def read_property(db, prod_id, field, first_list_item=False):
    read_result = read(db, prod_id, [field])
    prod_property = read_result[field]
    if first_list_item:
        return prod_property[0]
    else:
        return prod_property


def category_id_from_name(name):
    return get_id('product.category', [('name', '=', name)])


def get_category_with_descendants(prod_id):
    return [prod_id] + get_category_descendants(prod_id)


@lru_cache(LRU_CACHE_MAX_ENTRIES)
def get_categories():
    return read_elements('product.category', [], ['parent_id', 'name'])

def get_category(prod_id):
    for c in get_categories():
        if c['id'] == prod_id:
            return c
    raise NotFound()


def get_category_children(prod_id):
    # IDs of all direct child categories
    for c in get_categories():
        if c['parent_id'] and c['parent_id'][0] == prod_id:
            yield c['id']


def get_category_descendants(prod_id):
    children = list(get_category_children(prod_id))
    descendants = children
    for x in children:
        descendants += get_category_descendants(x)
    return descendants


@lru_cache(LRU_CACHE_MAX_ENTRIES)
def get_supplier_info():
    return read_elements('product.supplierinfo', [])


def get_supplier_info_from_product(p):
    # input: product data dict
    # TODO only shows first supplier
    if len(p['seller_ids']) == 0:
        raise NotFound
    for i in get_supplier_info():
        if i['id'] == p['seller_ids'][0]:
            return i
    raise NotFound()


def import_products_oerp(data, extra_filters=None, columns=None):
    # TODO code vs default_code -> what's the difference?
    if not columns:
        columns = []
    if not extra_filters:
        extra_filters = []
    columns = deepcopy(columns)
    if columns:
        columns += ["name", "description", "code", "default_code", "list_price", "active", "sale_ok", "categ_id", "uom_id", "manufacturer",
                    "manufacturer_pname", "manufacturer_pref", "seller_ids"]
    print "OERP Import"
    prod_ids = oerp.search('product.product', [('default_code', '!=', False)] + extra_filters)
    print "reading {} products from OERP, this may take some minutes...".format(len(prod_ids))
    prods = []

    def split_list(prod_list, chunk_size):
        return [prod_list[offs:offs + chunk_size] for offs in range(0, len(prod_list), chunk_size)]

    # columns starting with _ are generated in this script and not from the DB
    query_columns = [col for col in columns if not col.startswith("_")]
    # read max. n products at once
    n = 45
    for prod_ids_slice in split_list(prod_ids, n):
        print "."
        prods += oerp.read('product.product', prod_ids_slice, query_columns,
                           context=oerp.context)
        time.sleep(2)

    # Only consider things with numerical PLUs in code field
    prods = filter(lambda p: str_to_int(p['code']) is not None, prods)

    # which units are only possible in integer amounts? (e.g. pieces, pages of paper)
    integer_uoms = oerp.search('product.uom', [('rounding', '=', 1)])

    for p in prods:
        # print p['code']
        if p['list_price'] == 0:
            # WORKAROUND: solange die Datenqualität so schlecht ist, werden Artikel mit Preis 0 erstmal ignoriert.
            continue
        if not p['active'] or not p['sale_ok']:
            continue
        p['code'] = "{:04d}".format(int(p['code']))
        p['categ'] = categ_id_to_list_of_names(p['categ_id'][0])
        p['categ_str'] = " / ".join(p['categ'])
        price_str = '{:.3f}'.format(p['list_price'])
        if price_str[-1] == "0":  # third digit only if nonzero
            price_str = price_str[:-1]
        p['_price'] = u'{} €'.format(price_str)
        p['input_mode'] = 'DECIMAL'
        if p['uom_id'][0] in integer_uoms:
            p['input_mode'] = 'INTEGER'
        p['uom'] = p['uom_id'][1]
        
        p['_name_and_description'] = p['name']
        if p['description']:
            p['_name_and_description'] += '\n' + p['description']
        
        # supplier and manufacturer info:
        p['_supplier_all_infos'] = ''
        try:
            p['_supplierinfo'] = get_supplier_info_from_product(p)
            if p['_supplierinfo']['name']:
                p['_supplier_name'] = p['_supplierinfo']['name'][1]
                p['_supplier_code'] = p['_supplierinfo']['product_code'] or ''
                p['_supplier_name_code'] = p['_supplier_name'] + ": " + p['_supplier_code']
                p['_supplier_all_infos'] += p['_supplier_name_code']
        except NotFound:
            pass
        if p['manufacturer']:
            p['_supplier_all_infos'] += ", Hersteller: {} ({}) {}" \
                .format(p['manufacturer'][1],
                        p['manufacturer_pref'] or '',
                        p['manufacturer_pname'] or '')

        data[p['code']] = p
    return data


def html_escape(x):
    return cgi.escape(x).encode('ascii', 'xmlcharrefreplace').replace("\n", "<br/>")


def tr(x, options=""):
    out = u"<tr {}>".format(options)
    for v in x:
        out += u"<td>{}</td>".format(html_escape(v))
    out += u"</tr>"
    return out


# fill the template file with data
def make_html_from_template(heading, content):
    filename = "template.html"
    f = open(filename, "r")
    out = f.read()
    f.close()
    out = out.replace("$HEADING", heading)
    out = out.replace("$REFRESHDATE", time.strftime("%x %X", time.localtime()))
    out = out.replace("$CONTENTTABLE", content)
    return out


def make_price_list_html(base_category, columns, column_names):
    if type(base_category) != int:
        base_category = category_id_from_name(base_category)
    categories = get_category_with_descendants(base_category)
    print categories
    data = import_products_oerp({}, [('categ_id', 'in', categories)], columns)

    def make_header(x):
        return column_names.get(x, x)

    content_table = tr([make_header(x) for x in columns], 'class="head"')
    product_list = data.values()
    product_list = natsort.natsorted(product_list, key=lambda x: [x['categ'], x['name']])
    current_category = None
    for p in product_list:
        if p['categ'] != current_category:
            current_category = p['categ']
            content_table += u'<tr class="newCateg">\n<td colspan="5">{}</td>\n</tr>\n'.format(
                html_escape(p["categ_str"]))
        row = []
        for w in columns:
            value = str(p.get(w, ""))
            row.append(value)
        content_table += tr(row)

    heading = "Preisliste " + " / ".join(categ_id_to_list_of_names(base_category))
    out = make_html_from_template(heading, content_table)
    return heading, out


def main():
    data = {}
    print data
    column_names = {"code": "Nr.", "_name_and_description": "Bezeichnung", "_price": "Preis", "uom": "Einheit",
                    "_supplier_name_code": "Lieferant", "_supplier_all_infos": "Lieferant / Hersteller",
                    "x_durchmesser": "D", "x_stirnseitig": "eintauchen?", "x_fraeserwerkstoff": "aus Material",
                    "x_fuerwerkstoff": "für Material"}
    default_cols = ["code", "_name_and_description", "_price", "uom", "_supplier_all_infos"]
    jobs = [  # ("Fräser", default_cols+["x_durchmesser", "x_stirnseitig", "x_fraeserwerkstoff", "x_fuerwerkstoff"]),
              ("CNC", default_cols),
              (228, default_cols),  # Fräsenmaterial
              ("Laser", default_cols),
              ("Schneideplotter", default_cols),
              ("Platinenfertigung", default_cols),
              ("Alle Produkte", default_cols)
    ]

    file_list = []
    for (cat, columns) in jobs:
        print cat
        (title, price_list) = make_price_list_html(cat, columns, column_names)
        if type(cat) == int:
            cat = str(cat)
        filename = "price_list-{}.html".format(re.sub(r'[^0-9a-zA-Z]', '_', cat))
        f = open("output/" + filename, "w")
        f.write(price_list)
        file_list.append((filename, title))
        f.close()

    f = open("output/index.html", "w")
    html_list = "<ul>"
    for (filename, title) in file_list:
        html_list += '<li><a href="{}">{}</a></li>'.format(filename, html_escape(title))
    html_list += "</ul>"
    html_list = make_html_from_template("Übersicht aller Preislisten", html_list)
    f.write(html_list)
    f.close()


if __name__ == '__main__':
    main()
