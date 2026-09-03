FROM quay.io/frrouting/frr:10.7.1

RUN apk add --no-cache tcpdump

COPY daemons /etc/frr/daemons
COPY frr.conf /etc/frr/frr.conf
COPY vtysh.conf /etc/frr/vtysh.conf

RUN chown frr:frr /etc/frr/daemons /etc/frr/frr.conf /etc/frr/vtysh.conf \
    && chmod 660 /etc/frr/daemons /etc/frr/frr.conf /etc/frr/vtysh.conf
