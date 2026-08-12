import assert from "node:assert/strict";
import test from "node:test";

import {
  SynchronizedCameraTimeline,
  TimelineError,
} from "../../../web/src/features/workbench-timeline/synchronized-camera-timeline.js";

const cameras = [
  {
    cameraId: 6,
    frames: [
      { contentType: "image/jpeg", filename: "camera-6-time-0.jpg" },
      { contentType: "image/jpeg", filename: "camera-6-time-1.jpg" },
      { contentType: "image/jpeg", filename: "camera-6-time-2.jpg" },
    ],
  },
  {
    cameraId: 0,
    frames: [
      { contentType: "image/png", filename: "camera-0-time-0.png" },
      { contentType: "image/png", filename: "camera-0-time-1.png" },
      { contentType: "image/png", filename: "camera-0-time-2.png" },
    ],
  },
  {
    cameraId: 2,
    frames: [
      { contentType: "image/jpeg", filename: "camera-2-time-0.jpg" },
      { contentType: "image/jpeg", filename: "camera-2-time-1.jpg" },
      { contentType: "image/jpeg", filename: "camera-2-time-2.jpg" },
    ],
  },
];

test("orders camera views by Camera ID without mutating the scene camera order", () => {
  const timeline = new SynchronizedCameraTimeline(cameras);

  assert.deepEqual(
    timeline.snapshot().cameras.map(({ cameraId, frame }) => [cameraId, frame.filename]),
    [
      [0, "camera-0-time-0.png"],
      [2, "camera-2-time-0.jpg"],
      [6, "camera-6-time-0.jpg"],
    ],
  );
  assert.deepEqual(cameras.map((camera) => camera.cameraId), [6, 0, 2]);
});

test("selecting one timeline time index updates every sorted camera view together", () => {
  const timeline = new SynchronizedCameraTimeline(cameras);

  const selected = timeline.selectTimeIndex(2);

  assert.equal(selected.timeIndex, 2);
  assert.equal(selected.frameCount, 3);
  assert.deepEqual(
    selected.cameras.map(({ cameraId, frame }) => [cameraId, frame.filename]),
    [
      [0, "camera-0-time-2.png"],
      [2, "camera-2-time-2.jpg"],
      [6, "camera-6-time-2.jpg"],
    ],
  );
});

test("rejects time indexes outside the synchronized camera frame range", () => {
  const timeline = new SynchronizedCameraTimeline(cameras);

  assert.throws(
    () => timeline.selectTimeIndex(3),
    (error: unknown) => error instanceof TimelineError && error.code === "TIME_INDEX_OUT_OF_RANGE",
  );
});
