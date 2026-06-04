package com.miniapp.gateway.sse;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.Optional;

@Component
@RequiredArgsConstructor
@Slf4j
public class JobReader {

  private final JdbcTemplate jdbc;

  public Optional<JobSnapshot> findById(String jobId) {
    try {
    JobSnapshot snapshot = jdbc.queryForObject(
        "SELECT id, job_type, status, progress, progress_stage, " +
          "result::text AS result_json, error, target_id, " +
          "extract(epoch from coalesce(finished_at, started_at, created_at)) AS updated_ts " +
          "FROM jobs WHERE id = ?",
        (rs, rowNum) -> new JobSnapshot(
          rs.getString("id"),
          rs.getString("job_type"),
          rs.getString("status"),
          rs.getInt("progress"),
          rs.getString("progress_stage"),
          rs.getString("result_json"),
          rs.getString("error"),
          rs.getString("target_id"),
          (long) rs.getDouble("updated_ts")
        ),
        jobId
    );
    return Optional.ofNullable(snapshot);
    } catch (EmptyResultDataAccessException e) {
    return Optional.empty();
    }
  }
}
