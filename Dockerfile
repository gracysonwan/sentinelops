# One Dockerfile for all Java services. Compose passes MODULE (e.g. order-service).
# Stage 1 builds every module once (Maven dependencies are cached between builds).
FROM maven:3.9.9-eclipse-temurin-17 AS build
WORKDIR /src
COPY pom.xml .
COPY sentinel-chaos sentinel-chaos
COPY order-service order-service
COPY payment-service payment-service
COPY inventory-service inventory-service
COPY remediation-engine remediation-engine
RUN --mount=type=cache,target=/root/.m2,sharing=locked \
    mvn -B -q -DskipTests package

# Stage 2: small runtime image with just the one service's jar.
FROM eclipse-temurin:17-jre
ARG MODULE
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /src/${MODULE}/target/${MODULE}-1.0.0.jar /app/app.jar
# Heap is capped at 256 MB so the memory-leak scenario reaches its limit in a few minutes.
ENV JAVA_OPTS="-Xms128m -Xmx256m"
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/app.jar"]
