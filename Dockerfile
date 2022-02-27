FROM ubuntu:18.04
RUN apt update && \
    apt -y --no-install-recommends install \
        python3-minimal python3-pip python3-setuptools python3-natsort python3-repoze.lru \
        git language-pack-de rsync && \
    python3 -m pip install oerplib
COPY . .
RUN python3 -m pip install --upgrade -r requirements.txt
ENTRYPOINT [ "./run.sh" ]