FROM anthillplatform/anthill-common:latest
RUN apt-get install -y git
WORKDIR /tmp
COPY anthill /tmp/anthill
COPY MANIFEST.in /tmp
COPY setup.py /tmp
RUN pip install --extra-index-url https://cdn.anthillplatform.org/python .
RUN rm -rf /tmp
ENTRYPOINT [ "python", "-m", "anthill.exec.server"]
