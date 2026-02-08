FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* /app/
RUN npm install

COPY . /app

CMD ["sh", "-c", "npm run build && rm -rf /frontend_dist/* && cp -r dist/* /frontend_dist && tail -f /dev/null"]
