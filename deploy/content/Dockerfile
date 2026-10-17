# Extend the already reviewed integration runtime; never include a device .env,
# database, recordings or task output in the build context.
ARG CONTENT_BASE_IMAGE
FROM ${CONTENT_BASE_IMAGE}
USER root
COPY requirements.txt /tmp/vinote-content-requirements.txt
RUN pip install --no-cache-dir -r /tmp/vinote-content-requirements.txt \
    && rm /tmp/vinote-content-requirements.txt
COPY app /srv/vinote/app
USER vinote
