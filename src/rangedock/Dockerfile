FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash ca-certificates curl dnsutils git iproute2 iputils-ping jq \
       less netcat-openbsd nmap openssh-client python3 ripgrep tmux vim-tiny \
       wget whois \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /bin/bash analyst \
    && mkdir -p /workspace \
    && chown analyst:analyst /workspace

USER analyst
ENV HOME=/home/analyst
WORKDIR /workspace
CMD ["sleep", "infinity"]
