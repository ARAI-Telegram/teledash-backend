#!/bin/bash
set -e

# 1. Start Elasticsearch in the background
echo "Starting Elasticsearch..."
/usr/local/bin/docker-entrypoint.sh elasticsearch &
ELASTIC_PID=$!

# Function to cleanup on exit
cleanup() {
    echo "Shutting down Elasticsearch..."
    kill $ELASTIC_PID 2>/dev/null || true
    wait $ELASTIC_PID 2>/dev/null || true
    exit
}

# Set up signal handlers for graceful shutdown
trap cleanup SIGTERM SIGINT

# 2. Wait for Elasticsearch to be ready
echo "Waiting for Elasticsearch to start..."
timeout=120
counter=0

until curl -s http://localhost:9200/_cluster/health >/dev/null 2>&1; do
    if [ $counter -ge $timeout ]; then
        echo "Elasticsearch failed to start within $timeout seconds"
        cleanup
    fi
    echo "Still waiting for Elasticsearch... (${counter}s)"
    sleep 2
    counter=$((counter + 2))
done

echo "Elasticsearch is ready! Running initialization script..."

# Set environment variable for the init script
export ELASTICSEARCH_URL="http://localhost:9200"

# 3. Run the initialization script
python3 /usr/local/bin/elasticsearch-init.py

if [ $? -eq 0 ]; then
    echo "Elasticsearch initialization completed successfully."
else
    echo "Elasticsearch initialization failed!"
    cleanup
fi

# Keep Elasticsearch running in the foreground
wait $ELASTIC_PID