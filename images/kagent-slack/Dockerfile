# Slack bridge for kagent (bot.py). Built by
# .github/workflows/kagent-slack-image.yaml; deployed by
# k8s/prod/kagent/slack-bot.yaml.
FROM python:3.13.18-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .

# The unit tests run as part of the build, so a failing test fails the image.
FROM base AS test
COPY requirements-dev.txt test_bot.py ./
RUN pip install --no-cache-dir -r requirements-dev.txt && python -m pytest -q && touch /tested

FROM base
# Depend on the test stage so BuildKit cannot skip it.
COPY --from=test /tested /tested
USER 65534:65534
CMD ["python", "-u", "bot.py"]
