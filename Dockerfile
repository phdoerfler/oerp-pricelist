# See https://hub.docker.com/r/frolvlad/alpine-python2/dockerfile
FROM alpine:3.14
RUN apk add --no-cache python2 && \
    python -m ensurepip && \
    rm -r /usr/lib/python*/ensurepip && \
    pip install --upgrade pip setuptools && \
    rm -r /root/.cache && \
    python2 -m pip install oerplib
COPY . .
RUN python2 -m pip install --upgrade -r requirements.txt
ENTRYPOINT [ "./run.sh" ]