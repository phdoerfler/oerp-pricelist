FROM ubuntu:18.04
RUN apt update && \
    apt -y --no-install-recommends install \
        python3-minimal python3-pip python3-setuptools python3-natsort python3-repoze.lru \
        git language-pack-de rsync && \
    python3 -m pip install oerplib
RUN git clone https://github.com/fau-fablab/oerp-pricelist /oerp-pricelist
WORKDIR /oerp-pricelist
RUN python3 -m pip install --upgrade -r requirements.txt
COPY config.ini config.ini
ENTRYPOINT [ "./run.sh" ]