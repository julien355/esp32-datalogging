# Tested on a test machine on 8 Nov 2026 (tutorial 3, Appendix C); not yet run on hermes-vps.
# Lean Open Energy Dashboard (OED) image for hermes-vps (docs/VPS-MEMORY.md).
# OED is used as it is: this file only builds it once, OFF the VPS, and runs it without build tools.
#
# Build on the laptop (Docker Desktop), from the repository root:
#   docker build -t arkan-oed:v1.0.0 --build-arg OED_REF=v1.0.0 server/deploy/oed
# Tutorial: docs/tutorials/3-OPEN-ENERGY-DASHBOARD.md, Part A.
#
# Node version: OED v1.0.0 pins node:16.13.2 in its containers/web/Dockerfile.
# Change NODE_TAG only together with OED_REF (the development branch uses node:18.17.1).

ARG NODE_TAG=16.13.2

# ---- Stage 1: build (needs 1 to 2 GB of RAM, so never on the VPS)
FROM node:${NODE_TAG} AS build
ARG OED_REF=v1.0.0
WORKDIR /usr/src/app
# The pinned release, without its git history. OED_COMMIT records the exact commit.
RUN git clone --depth 1 --branch "${OED_REF}" https://github.com/OpenEnergyDashboard/OED.git . \
 && git rev-parse HEAD > OED_COMMIT \
 && rm -rf .git
# Same install flags as OED's src/scripts/installOED.sh
RUN npm ci --loglevel=warn --legacy-peer-deps
# Builds the web page bundle into src/client/public/app/ (OED's webpack.config.js)
RUN npm run webpack:build
# Drop the build tools (webpack, typescript, test tools): only runtime packages stay
RUN npm prune --production --legacy-peer-deps

# ---- Stage 2: runtime (small image, no compiler, no webpack)
FROM node:${NODE_TAG}-slim
WORKDIR /usr/src/app
COPY --from=build /usr/src/app /usr/src/app
# Writable places only: the log file and the CSV upload folder (src/server/routes/csv.js)
RUN mkdir -p log src/server/tmp/uploads/csvPipeline \
 && chown -R node:node log src/server/tmp
USER node
EXPOSE 3000
# OED's own start script runs "npm run createdb" at every start (it does nothing harmful on an
# existing database), then "npm run start" (node ./src/bin/www). We do the same, without npm ci
# and without webpack.
CMD ["sh", "-c", "npm run --silent createdb && exec node ./src/bin/www"]
