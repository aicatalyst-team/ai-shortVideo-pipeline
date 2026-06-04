package com.miniapp.gateway.sse;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class JobSnapshotTest {

  private JobSnapshot snapshot(int progress, String status, String stage) {
    return new JobSnapshot("J1", "regenerate_clip", status, progress, stage,
      null, null, "CLIPTEST", 0L);
  }

  @Test
  void isTerminal_recognizesDoneFailedCancelled() {
    assertThat(snapshot(100, "done", "done").isTerminal()).isTrue();
    assertThat(snapshot(50, "failed", "x").isTerminal()).isTrue();
    assertThat(snapshot(50, "cancelled", "x").isTerminal()).isTrue();
    assertThat(snapshot(50, "running", "x").isTerminal()).isFalse();
    assertThat(snapshot(0, "queued", "x").isTerminal()).isFalse();
  }

  @Test
  void fingerprint_changesWithStatusOrProgress() {
    String first = snapshot(30, "running", "generating").fingerprint();
    String second = snapshot(30, "running", "generating").fingerprint();
    String changedProgress = snapshot(31, "running", "generating").fingerprint();
    String changedStatus = snapshot(30, "done", "done").fingerprint();

    assertThat(first).isEqualTo(second);
    assertThat(first).isNotEqualTo(changedProgress);
    assertThat(first).isNotEqualTo(changedStatus);
  }

  @Test
  void eventType_mapping() {
    assertThat(snapshot(0, "queued", "queued").eventType()).isEqualTo("started");
    assertThat(snapshot(30, "running", "x").eventType()).isEqualTo("progress");
    assertThat(snapshot(100, "done", "done").eventType()).isEqualTo("completed");
    assertThat(snapshot(30, "failed", "x").eventType()).isEqualTo("failed");
    assertThat(snapshot(30, "cancelled", "x").eventType()).isEqualTo("cancelled");
  }

  @Test
  void toMap_includesTraceIdWhenProvided() {
    var map = snapshot(30, "running", "x").toMap("trace-abc");
    assertThat(map).containsEntry("job_id", "J1");
    assertThat(map).containsEntry("progress", 30);
    assertThat(map).containsEntry("trace_id", "trace-abc");
  }

  @Test
  void toMap_omitsTraceIdWhenEmpty() {
    var map = snapshot(30, "running", "x").toMap("");
    assertThat(map).doesNotContainKey("trace_id");
  }
}
