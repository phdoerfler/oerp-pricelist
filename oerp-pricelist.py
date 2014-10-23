#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

# (C) Max Gaukler, Julian Hammer 2014
# unlimited usage allowed, see LICENSE file

# Dependencies

from lxml import etree
from copy import deepcopy
import sys, os, inspect
import StringIO
import math
import urllib2
import re
from decimal import Decimal
from pprint import pprint
import oerplib
import locale
from ConfigParser import ConfigParser
import codecs
import cgi
import time
# sudo pip install functools32 natsort # for caching functionality not present in python2 functools
from functools32 import lru_cache
import natsort


# switching to german:
locale.setlocale(locale.LC_ALL, "de_DE.UTF-8")
reload(sys).setdefaultencoding('UTF-8') # somehow doesn't work

if (sys.stdout.encoding != "UTF-8"):            
    print sys.stdout.encoding
    print >> sys.stderr, "please use a UTF-8 locale, e.g. LANG=en_US.UTF-8" 
    exit(1)

cfg = ConfigParser({})
cfg.readfp(codecs.open('config.ini', 'r', 'utf8'))

oerp = oerplib.OERP(server=cfg.get('openerp', 'server'), protocol='xmlrpc+ssl',
                    database=cfg.get('openerp', 'database'), port=cfg.getint('openerp', 'port'),
                    version=cfg.get('openerp', 'version'))
user = oerp.login(user=cfg.get('openerp', 'user'), passwd=cfg.get('openerp', 'password'))
oerpContext=oerp.context

def str_to_int(s, fallback=None):
    try:
        return int(s)
    except ValueError:
        return fallback





@lru_cache()
def categ_id_to_list_of_names(c_id):
    # TODO make this faster by once fetching the list of all categories
    categ = getCategory(c_id)
    
    if categ['parent_id'] == False or \
           categ['parent_id'][0] == cfg.getint('openerp', 'base_category_id'):
        return [categ['name']]
    else:
        return categ_id_to_list_of_names(categ['parent_id'][0])+[categ['name']]
        

class NotFound(Exception):
    pass

def getId(db, filter):
    ids=getIds(db, filter)
    if not ids:
       raise NotFound("cannot find {} from search {}".format(db, str(filter)))
    assert len(ids)==1, "found more than one {} from search {}".format(db, str(filter))
    return ids[0]

def getIds(db, filter):
    return oerp.search(db, filter, context=oerpContext)

def read(db, id, fields=[]):
    assert type(id)=="int",  "read is only for one element. see also: readElements() for reading multiple elements with a filter"
    readResult=oerp.read(db, [id], fields, context=oerpContext)
    if len(readResult)!=1:
        raise NotFound()
    return readResult[0]

def write(db, id, data):
    return oerp.write(db, [id], data, context=oerpContext)

def create(db, data):
    return oerp.create(db, data, context=oerpContext)

def readElements(db, filter, fields=[]):
    return oerp.read(db, getIds(db, filter), fields, context=oerpContext)

def readProperty(db, id, field, firstListItem=False):
    readResult=read(db, id, [field])
    property=readResult[field]
    if firstListItem:
        return property[0]
    else:
        return property

def categoryIdFromName(name):
    return getId('product.category', [('name', '=', name)])

def getCategoryWithDescendants(id):
    return [id] + getCategoryDescendants(id)

@lru_cache()
def getCategories():
    return readElements('product.category', [], ['parent_id', 'name'])

def getCategory(id):
    for c in getCategories():
        if c['id'] == id:
            return c
    raise NotFound()

def getCategoryChildren(id):
    # IDs of all direct child categories
    for c in getCategories():
        if c['parent_id'] and c['parent_id'][0]==id:
            yield c['id']

def getCategoryDescendants(id):
    children=list(getCategoryChildren(id))
    descendants=children
    for x in children:
        descendants += getCategoryDescendants(x)
    return descendants

@lru_cache()
def getSupplierInfos():
    return readElements('product.supplierinfo', [])
    
def getSupplierInfoFromProduct(id):
    # TODO only shows first supplier
    for i in getSupplierInfos():
        if i['product_id'][0] == id:
            return i
    raise NotFound()

def importProdukteOERP(data, extra_filters=[]):
    print "OERP Import"
    prod_ids = oerp.search('product.product', [('default_code', '!=', False)]+extra_filters)
    print "reading {} products from OERP, this may take some minutes...".format(len(prod_ids))
    prods = []
    def SplitList(list, chunk_size):
        return [list[offs:offs+chunk_size] for offs in range(0, len(list), chunk_size)]
    # read max. 100 products at once
    for prod_ids_slice in SplitList(prod_ids, 100):
        print "."
        prods += oerp.read('product.product', prod_ids_slice, [],
            context=oerp.context)
    
    # Only consider things with numerical PLUs in code field
    prods = filter(lambda p: str_to_int(p['code']) is not None, prods)
    
    # which units are only possible in integer amounts? (e.g. pieces, pages of paper)
    integer_uoms = oerp.search('product.uom', [('rounding', '=', 1)])
    
    for p in prods:
        #print p['code']
        if p['list_price']==0:
            # WORKAROUND: solange die Datenqualität so schlecht ist, werden Artikel mit Preis 0 erstmal ignoriert.
            continue
        if not p['active'] or not p['sale_ok']:
            continue
        p['code'] = int(p['code'])
        p['categ'] = categ_id_to_list_of_names(p['categ_id'][0])
        p['categ_str'] = " / ".join(p['categ'])
        priceStr='{:.3f}'.format(p['list_price'])
        if priceStr[-1]=="0": # third digit only if nonzero
            priceStr=priceStr[:-1]
        p['price']=u'{} €'.format(priceStr)
        p['input_mode']='DECIMAL'
        if p['uom_id'][0] in integer_uoms:
            p['input_mode'] = 'INTEGER'
        p['uom']=p['uom_id'][1]
        
        # supplier and manufacturer info:
        p['supplier_all_infos']=''
        try:
            p['supplierinfo']=getSupplierInfoFromProduct(p['id'])
            if p['supplierinfo']['name']:
                p['supplier_name']=p['supplierinfo']['name'][1]
                p['supplier_code']=p['supplierinfo']['product_code'] or ''
                p['supplier_name_code']=p['supplier_name'] + ": " + p['supplier_code']
                p['supplier_all_infos'] += p['supplier_name_code']
        except NotFound:
            pass
        if p['manufacturer']:
            p['supplier_all_infos'] += ", Hersteller: {} ({}) {}" \
                                        .format(p['manufacturer'][1], 
                                                p['manufacturer_pref'] or '', 
                                                p['manufacturer_pname'] or '')
    
        data[p['code']]=p
    return data

def htmlescape(x):
    return cgi.escape(x).encode('ascii', 'xmlcharrefreplace')

def TR(x, options=""):
    out=u"<tr {}>".format( options)
    for v in x:
        out+=u"<td>{}</td>".format(htmlescape(v))
    out+=u"</tr>"
    return out

def makePricelistHtml(baseCategory, columns, columnNames):
    if type(baseCategory) != int:
        baseCategory=categoryIdFromName(baseCategory)
    categories=getCategoryWithDescendants(baseCategory)
    print categories
    data = importProdukteOERP({}, [('categ_id', 'in', categories)])
    
    filename="sheme.html"
    f=open(filename, "r")
    out = u""
    out = f.read()
    f.close()

    def makeHeader(x):
        return columnNames.get(x, x)
    contenttable = TR([makeHeader(x) for x in columns], 'class="head"')
    productlist=data.values()
    productlist=natsort.natsorted(productlist, key=lambda x: [x['categ'], x['name']])
    currentCategory=None
    for p in productlist:
        if p['categ'] != currentCategory:
            currentCategory=p['categ']
            contenttable += u'<tr class="newCateg">\n<td colspan="5">{}</td>\n</tr>\n'.format(htmlescape(p["categ_str"]))
        row=[]
        for w in columns:
            value=str(p.get(w, ""))
            row.append(value)
        contenttable += TR(row)

    out = out.replace("$CATEGORY", str(baseCategory))
    out = out.replace("$REFRESHDATE", time.strftime("%x %X",time.localtime()))
    out = out.replace("$CONTENTTABLE", contenttable)
    return out

def main():    
    data = {}
    
    print data
    columnNames={"code":"Nr.", "name":"Bezeichnung", "price":"Preis", "uom":"Einheit", "supplier_name_code":"Lieferant", "supplier_all_infos":"Lieferant / Hersteller", 
                 "x_durchmesser":"D", "x_stirnseitig":"eintauchen?", "x_fraeserwerkstoff":"aus Material", "x_fuerwerkstoff":"für Material"}
    defaultCols=["code", "name", "price", "uom", "supplier_all_infos"]
    jobs= [ # ("Fräser", defaultCols+["x_durchmesser", "x_stirnseitig", "x_fraeserwerkstoff", "x_fuerwerkstoff"]), 
            #("CNC", defaultCols),
            (228, defaultCols), # Fräsenmaterial
            #("Schneideplotter", defaultCols), 
            #("Alle Produkte", defaultCols)
          ]
    for (cat, columns) in jobs:
        print cat
        pricelist=makePricelistHtml(cat, columns, columnNames)
        if type(cat)==int:
            cat=str(cat)
        filename="output/pricelist-{}.html".format(re.sub(r'[^0-9a-zA-Z]', '_', cat))
        f=open(filename, "w")
        f.write(pricelist)
        f.close()

if __name__ == '__main__':
    main()
