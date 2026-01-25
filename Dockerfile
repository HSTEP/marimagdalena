# --- Stage 1: Build the Frontend (Node.js) ---
# Uses a Node.js image to build your frontend application.
# This stage is named 'builder' so its output can be referenced later.
FROM node:20-alpine AS builder
WORKDIR /app
# Copy source files for the frontend
COPY src /app/src
# Copy package.json and package-lock.json first to leverage Docker's build cache
# This means npm install only runs if these files change.
COPY mariadmin/package.json mariadmin/package-lock.json ./
# Install Node.js dependencies
RUN npm install
# Copy the rest of the mariadmin directory
COPY mariadmin/ .
# Run the build command for your frontend application
# This typically outputs static files to a 'dist' or 'build' directory.
RUN npm run build

# --- Stage 2: Build the Final Python Image with Nginx ---
# Starts with a Python slim image for a smaller final image size.
FROM python:3.11-slim
WORKDIR /app

# Install Nginx, Node.js, npm, and other necessary packages
# `apt-get update` refreshes the package list.
# `apt-get install -y nginx curl` installs Nginx and curl.
# Node.js and npm are needed to run the React Admin dev server.
RUN apt-get update && apt-get install -y \
    nginx \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies using uv
# Copy pyproject.toml first for caching
COPY pyproject.toml .
# Install uv package manager
RUN pip install uv
# Install Python project dependencies into the system environment
RUN uv pip install --system --no-cache .

# Copy Python application files
COPY api.py .
COPY build.py .
COPY src ./src
COPY images ./images

# Copy mariadmin source code for the dev server
COPY mariadmin/ ./mariadmin/
# Install mariadmin dependencies for the dev server
RUN cd mariadmin && npm install

# Copy the built static files from the 'builder' stage
# This is where Nginx will look for your index.html and other static assets.
COPY --from=builder /app/dist ./dist

# Copy the custom Nginx configuration file.
COPY nginx.conf /etc/nginx/nginx.conf

# Copy the entrypoint script and make it executable.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Expose ports: 8000 (API), 3000 (Static), 5173 (Dev)
EXPOSE 8000
EXPOSE 3000
EXPOSE 5173

# Set the custom entrypoint script as the default command to run when the container starts.
CMD ["/usr/local/bin/entrypoint.sh"]
