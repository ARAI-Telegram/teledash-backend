# For more information, please refer to https://aka.ms/vscode-docker-python
FROM python:3.11.13-slim

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# "procps" for pkill
# "protobuf-compiler", "g++" for cld3 build
# "wget" to download gpg key for custom repo
# "gnupg" for installing gpg key for custom repo
RUN apt-get update && apt-get install -y procps g++ protobuf-compiler gnupg wget 

# Install shared pip requirements
COPY ./common/requirements.txt .
RUN python -m pip install -r requirements.txt

# Install pip requirements
COPY ./worker/requirements.txt .
RUN python -m pip install -r requirements.txt

# clean up
# remove "protobuf-compiler", "g++" for cld3 build
RUN apt remove g++ protobuf-compiler wget -y
# remove git later

WORKDIR /app
COPY ./worker/ /app/

# Creates a non-root user with an explicit UID and adds permission to access the /app folder
# For more info, please refer to https://aka.ms/vscode-docker-python-configure-containers
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app

# Persist bash history
ARG USERNAME=appuser

RUN SNIPPET="export PROMPT_COMMAND='history -a' && export HISTFILE=/commandhistory/.bash_history" \
    && mkdir /commandhistory \
    && touch /commandhistory/.bash_history \
    && chown -R $USERNAME /commandhistory \
    && echo $SNIPPET >> "/home/$USERNAME/.bashrc"

# Create tmp data directory with proper ownership
RUN mkdir -p /app/tmp \
    && chown -R $USERNAME /app/tmp

# Switch to non-root user
USER appuser
