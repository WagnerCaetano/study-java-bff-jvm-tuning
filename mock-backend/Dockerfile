FROM node:20-alpine

WORKDIR /app

COPY package.json ./
COPY server.js ./

EXPOSE 8081

HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8081/health || exit 1

CMD ["node", "server.js"]
