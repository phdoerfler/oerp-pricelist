oerp-pricelist
==============

Export a HTML pricelist from OERP

setup
-----

```sh
# apt packages are not required but recommended
apt-get install python-repoze.lru python-natsort
pip install --upgrade -r requirements.txt

cp config.ini.example config.ini
```

You can write your own login data to `config.ini`

For progress bars:

```sh
docker-compose build pricelist
docker-compose run pricelist
```

or

```sh
docker-compose up --build
```

License
-------

[Unilicense](LICENSE)
