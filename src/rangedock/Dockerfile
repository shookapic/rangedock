FROM kalilinux/kali-rolling AS base

LABEL org.opencontainers.image.source="https://github.com/shookapic/rangedock"
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash ca-certificates curl dnsutils git iproute2 iputils-ping jq \
       less netcat-openbsd nmap openssh-client openvpn python3 ripgrep \
       tmux vim-tiny wget whois \
    && rm -rf /var/lib/apt/lists/* \
    && setcap -r /usr/lib/nmap/nmap \
    && ln -s /usr/lib/nmap/nmap /usr/local/bin/nmap \
    && useradd --create-home --uid 1000 --shell /bin/bash analyst \
    && mkdir -p /workspace \
    && chown analyst:analyst /workspace

USER analyst
ENV HOME=/home/analyst
WORKDIR /workspace
CMD ["sleep", "infinity"]

FROM base AS web
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       john hydra sqlmap ffuf gobuster nikto dirb whatweb wfuzz \
       feroxbuster dnsrecon tcpdump socat proxychains4 \
       seclists wordlists \
    && rm -rf /var/lib/apt/lists/*
USER analyst

FROM web AS desktop
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       novnc websockify openbox x11vnc xterm xvfb \
    && rm -rf /var/lib/apt/lists/*
COPY desktop-start /usr/local/bin/rangedock-desktop-start
RUN chmod 755 /usr/local/bin/rangedock-desktop-start
USER analyst
EXPOSE 6080
CMD ["rangedock-desktop-start"]
