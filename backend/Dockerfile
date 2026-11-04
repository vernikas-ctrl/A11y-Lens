# The backend, as a container. Task 10.1.
#
# Playwright needs system browser libraries that a plain Python image does not
# have, and a missing one does not fail the build -- it fails at the first
# scan, in production, with a message about a shared object nobody recognises.
# That is the single most common way this deploy goes wrong, so the browser and
# its libraries are installed here, at build time, and the build fails loudly
# if they cannot be.
#
# Base image: python:3.14-slim, matching the version pinned in the project
# exactly. The official Playwright image (mcr.microsoft.com/playwright/python)
# ships the browsers ready-made, which is tempting, but it carries Ubuntu's
# Python -- 3.12 at the time of writing -- and a deploy running a different
# Python from the one every test ran against is a difference waiting to matter.
# Installing the browser ourselves costs one build step and keeps one version.

FROM python:3.14-slim

# Logs go straight out rather than sitting in a buffer. Without this, a crash
# can lose the lines that explain it, which on a host you cannot attach a
# debugger to is most of what you have.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Browsers outside the home directory, so the non-root user below can read
    # them. The default location is ~/.cache, which belongs to whoever ran the
    # install -- root -- and would be unreadable after the USER switch.
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Requirements before the application code, so editing a source file does not
# invalidate the layer that installs Chromium. That layer takes minutes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# --with-deps is the whole point of this line: it runs Playwright's own list of
# apt packages for the browser, which is kept correct by the people who build
# the browser. Hand-maintaining that list is how the shared-object failure
# happens. Only chromium is installed -- the scanner uses nothing else, and
# Firefox and WebKit would add gigabytes to the image for no reason.
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app

# Not root. Cloud Run would happily run this as root; a scanner that loads
# arbitrary web pages in a browser is exactly the kind of program where that
# is worth the two extra lines.
RUN useradd --create-home --uid 10001 scanner \
    && chown -R scanner:scanner /ms-playwright
USER scanner

# Cloud Run injects PORT and will fail the deploy if the container listens
# anywhere else. The default matches Cloud Run's own default, so `docker run`
# with no PORT set behaves the same way locally.
#
# Shell form, so ${PORT} is expanded; `exec` so uvicorn becomes PID 1 and
# receives the SIGTERM that tells it to shut the browser down cleanly rather
# than being killed ten seconds later.
#
# One worker on purpose. Each worker is a separate Chromium, and the memory
# measurement in DECISIONS.md is for one.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
