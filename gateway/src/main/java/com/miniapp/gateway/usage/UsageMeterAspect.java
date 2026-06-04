package com.miniapp.gateway.usage;

import com.miniapp.gateway.llm.AllProvidersFailedException;
import com.miniapp.gateway.llm.BusinessErrorException;
import com.miniapp.gateway.llm.FallbackAttempt;
import com.miniapp.gateway.llm.LlmCallWriter;
import com.miniapp.gateway.llm.LlmChatRequest;
import com.miniapp.gateway.llm.RoutingResult;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Mono;

import java.util.List;

@Aspect
@Component
@RequiredArgsConstructor
@Slf4j
public class UsageMeterAspect {

  private final LlmCallWriter writer;

  @Around("@annotation(com.miniapp.gateway.usage.MeasureLlmCall)")
  public Object measure(ProceedingJoinPoint pjp) throws Throwable {
    LlmChatRequest req = extractRequest(pjp.getArgs());
    String traceId = MDC.get("traceId");
    if (traceId == null) {
    traceId = "";
    }

    Object result;
    try {
    result = pjp.proceed();
    } catch (Throwable e) {
    recordFailureFromException(req, e, traceId);
    throw e;
    }

    if (result instanceof Mono<?> mono) {
    String finalTraceId = traceId;
    LlmChatRequest finalReq = req;
    return mono
        .doOnSuccess(value -> {
        if (value instanceof RoutingResult routingResult && finalReq != null) {
          writer.recordCall(finalReq, routingResult, finalTraceId);
        }
        })
        .doOnError(e -> recordFailureFromException(finalReq, e, finalTraceId));
    }
    return result;
  }

  private LlmChatRequest extractRequest(Object[] args) {
    for (Object arg : args) {
    if (arg instanceof LlmChatRequest request) {
      return request;
    }
    }
    log.warn("[usage-aspect] no LlmChatRequest found; llm call will not be recorded");
    return null;
  }

  private void recordFailureFromException(LlmChatRequest req, Throwable e, String traceId) {
    if (req == null) {
    return;
    }
    List<FallbackAttempt> chain = extractChain(e);
    if (chain != null) {
    writer.recordFailure(req, chain, traceId);
    }
  }

  private List<FallbackAttempt> extractChain(Throwable e) {
    if (e instanceof AllProvidersFailedException ex) {
    return ex.getChain();
    }
    if (e instanceof BusinessErrorException ex) {
    return ex.getChain();
    }
    return null;
  }
}
