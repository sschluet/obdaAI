# Network-free rendering of an operator-approved snapshot. Never a live browsing proxy.
FROM mcr.microsoft.com/playwright:v1.62.1-noble@sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e
WORKDIR /runner
COPY package.json pnpm-lock.yaml ./
RUN npm install -g pnpm@11.19.0 --ignore-scripts && pnpm install --frozen-lockfile --ignore-scripts --prod && npm cache clean --force
COPY runner.mjs ./
ENV HOME=/tmp
USER 10001:10001
ENTRYPOINT ["node", "runner.mjs"]
