FROM ubuntu:18.04
RUN apt update && \
    apt -y --no-install-recommends install \
        python3-minimal python-pip python-setuptools python-natsort python-repoze.lru \
        git language-pack-de rsync && \
    pip3 install oerplib
RUN git clone https://github.com/fau-fablab/oerp-pricelist /oerp-pricelist
WORKDIR /oerp-pricelist
RUN pip install --upgrade -r requirements.txt
COPY config.ini config.ini
ENTRYPOINT [ "./run.sh" ]