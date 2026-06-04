FROM docker.m.daocloud.io/library/maven:3.9-eclipse-temurin-21 AS build

WORKDIR /build
COPY .mvn/settings.xml /root/.m2/settings.xml
COPY pom.xml .
RUN mvn -B dependency:go-offline

COPY src ./src
RUN mvn -B package -DskipTests

FROM docker.m.daocloud.io/library/eclipse-temurin:21-jre-alpine

WORKDIR /app

RUN addgroup -S spring && adduser -S spring -G spring
USER spring:spring

COPY --from=build /build/target/ai-platform-gateway-*.jar /app/app.jar

EXPOSE 8080

ENV JAVA_OPTS="-XX:+UseG1GC -XX:MaxRAMPercentage=70 -Dfile.encoding=UTF-8"

ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/app.jar"]
