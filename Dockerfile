FROM python:3.11-slim

WORKDIR /app

COPY ./ user_agent/

WORKDIR /app/user_agent

# Work IQ MCP is a Node.js-based MCP server (runs via npx)
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

RUN if [ -f requirements.txt ]; then \
        pip install -r requirements.txt; \
    else \
        echo "No requirements.txt found"; \
    fi

EXPOSE 8088

# Set default ASP.NET Core environment variables
ENV ASPNETCORE_URLS=http://+:8088
ENV ASPNETCORE_ENVIRONMENT=Production

CMD ["python", "container.py"]
