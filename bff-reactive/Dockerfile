# Build stage
FROM maven:3.9-eclipse-temurin-24 AS build
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline -B
COPY src ./src
RUN mvn package -DskipTests -B

# Runtime stage
FROM eclipse-temurin:24-jre-alpine
WORKDIR /app

# Create non-root user
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

COPY --from=build /app/target/*.jar app.jar

# Create results directory for GC logs
RUN mkdir -p /results && chown -R appuser:appgroup /results /app

USER appuser

EXPOSE 8080

# Default JVM flags (can be overridden via environment variables)
# GC logs are written to /results/ which is mounted as a volume
ENV JAVA_OPTS="-XX:+UseParallelGC \
  -XX:NewRatio=1 \
  -XX:SurvivorRatio=6 \
  -Xms1536m \
  -Xmx1536m \
  -Xlog:gc*:file=/results/gc.log:time,uptime,level,tags:filecount=5,filesize=10m"

ENTRYPOINT ["sh", "-c", "java ${JAVA_OPTS} -jar app.jar"]
