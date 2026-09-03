FROM alpine:3.22

RUN apk add --no-cache \
      bash \
      ca-certificates \
      coreutils \
      curl \
      libxml2-utils \
      openssh-client \
      python3 \
      sshpass \
      unzip

WORKDIR /workspace
ENTRYPOINT ["/workspace/infra/labctl/labctl.sh"]
