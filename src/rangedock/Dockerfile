FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash ca-certificates curl dnsutils git iproute2 iputils-ping jq \
       less netcat-openbsd nmap openssh-client python3 ripgrep tmux vim-tiny \
       wget whois \
       john hydra sqlmap ffuf gobuster nikto dirb whatweb wfuzz \
       feroxbuster dnsrecon tcpdump socat proxychains4 \
       seclists wordlists \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /bin/bash analyst \
    && mkdir -p /workspace \
    && chown analyst:analyst /workspace

RUN setcap -r /usr/lib/nmap/nmap \
    && ln -s /usr/lib/nmap/nmap /usr/local/bin/nmap

USER analyst
ENV HOME=/home/analyst
WORKDIR /workspace
CMD ["sleep", "infinity"]
