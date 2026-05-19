ARG NODE_BASE_IMAGE=node:20-alpine
FROM ${NODE_BASE_IMAGE}

WORKDIR /app

COPY frontend/package*.json ./
RUN npm install

COPY frontend/ ./

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
