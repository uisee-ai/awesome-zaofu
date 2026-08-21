function assertVector(value, length, name) {
  if (!Array.isArray(value) || value.length !== length || value.some((item) => !Number.isFinite(item))) {
    throw new TypeError(`${name} must contain exactly ${length} finite numbers`);
  }
}

function assertMatrix(value, rows, columns, name) {
  if (!Array.isArray(value) || value.length !== rows) {
    throw new TypeError(`${name} must contain exactly ${rows} rows`);
  }
  value.forEach((row, index) => assertVector(row, columns, `${name}[${index}]`));
}

function transformPoint4(point, matrix, name) {
  assertVector(point, 3, `${name}.point`);
  assertMatrix(matrix, 4, 4, `${name}.matrix`);
  const homogeneous = [point[0], point[1], point[2], 1];
  const transformed = matrix.map((row) => row.reduce((sum, coefficient, index) => sum + coefficient * homogeneous[index], 0));
  if (transformed[3] === 0) throw new RangeError(`${name} produced a zero homogeneous divisor`);
  return transformed.slice(0, 3).map((value) => value / transformed[3]);
}

function transformPoint3(point, matrix, name) {
  assertVector(point, 3, `${name}.point`);
  assertMatrix(matrix, 3, 3, `${name}.matrix`);
  return matrix.map((row) => row.reduce((sum, coefficient, index) => sum + coefficient * point[index], 0));
}

function euclideanResidual(actual, expected) {
  assertVector(actual, expected.length, "actual");
  assertVector(expected, expected.length, "expected");
  return Math.hypot(...actual.map((value, index) => value - expected[index]));
}

export function transformNuScenesLidarToCamera(point, transforms) {
  const orderedTransforms = [
    ["lidar_to_ego", transforms?.lidar_to_ego],
    ["ego_to_global_at_lidar", transforms?.ego_to_global_at_lidar],
    ["global_to_ego_at_camera", transforms?.global_to_ego_at_camera],
    ["ego_to_camera", transforms?.ego_to_camera],
  ];
  return orderedTransforms.reduce(
    (current, [name, matrix]) => transformPoint4(current, matrix, `nuscenes.${name}`),
    [...point],
  );
}

export function openLaneWaymoToStandardCamera(point, waymoToStandardCamera) {
  return transformPoint3(point, waymoToStandardCamera, "openlane.waymo_to_standard_camera");
}

export function projectCameraPoint(point, cameraIntrinsic) {
  assertVector(point, 3, "camera_point");
  assertMatrix(cameraIntrinsic, 3, 3, "camera_intrinsic");
  const [x, y, depth] = point;
  if (depth <= 0) return null;
  const projected = transformPoint3(point, cameraIntrinsic, "camera_projection");
  return {
    pixel: [projected[0] / projected[2], projected[1] / projected[2]],
    depth,
  };
}

export function measureCoordinateFixture(fixture, fixtureSha256) {
  if (fixture?.schema_version !== "coordinate-golden.v1") throw new TypeError("unsupported coordinate fixture schema");
  if (!/^[0-9a-f]{64}$/.test(fixtureSha256)) throw new TypeError("fixtureSha256 must be lowercase sha256 hex");

  const nuscenesCamera = transformNuScenesLidarToCamera(fixture.nuscenes.point_lidar_m, fixture.nuscenes.transforms);
  const nuscenesProjection = projectCameraPoint(nuscenesCamera, fixture.nuscenes.camera_intrinsic);
  if (!nuscenesProjection) throw new RangeError("nuScenes golden point unexpectedly fell behind the camera");

  const openlaneCamera = openLaneWaymoToStandardCamera(
    fixture.openlane.point_waymo_camera_m,
    fixture.openlane.waymo_to_standard_camera,
  );
  const openlaneProjection = projectCameraPoint(openlaneCamera, fixture.openlane.camera_intrinsic);
  if (!openlaneProjection) throw new RangeError("OpenLane golden point unexpectedly fell behind the camera");

  return {
    schema_version: "coordinate-spike-report.v1",
    fixture_id: fixture.fixture_id,
    fixture_sha256: fixtureSha256,
    deterministic: true,
    method: fixture.method,
    candidate_thresholds: fixture.candidate_thresholds,
    measurements: {
      nuscenes: {
        input_lidar_m: fixture.nuscenes.point_lidar_m,
        expected_camera_m: fixture.nuscenes.expected.point_camera_m,
        actual_camera_m: nuscenesCamera,
        translation_residual_m: euclideanResidual(nuscenesCamera, fixture.nuscenes.expected.point_camera_m),
        expected_pixel: fixture.nuscenes.expected.pixel,
        actual_pixel: nuscenesProjection.pixel,
        projection_residual_px: euclideanResidual(nuscenesProjection.pixel, fixture.nuscenes.expected.pixel),
        depth_m: nuscenesProjection.depth,
      },
      openlane: {
        input_waymo_camera_m: fixture.openlane.point_waymo_camera_m,
        expected_standard_camera_m: fixture.openlane.expected.point_standard_camera_m,
        actual_standard_camera_m: openlaneCamera,
        translation_residual_m: euclideanResidual(openlaneCamera, fixture.openlane.expected.point_standard_camera_m),
        expected_pixel: fixture.openlane.expected.pixel,
        actual_pixel: openlaneProjection.pixel,
        projection_residual_px: euclideanResidual(openlaneProjection.pixel, fixture.openlane.expected.pixel),
        depth_m: openlaneProjection.depth,
      },
    },
    candidate_evaluation: {
      policy: "record_only_not_a_pass_gate",
      translation_candidate_m: fixture.candidate_thresholds.translation_m,
      projection_candidate_px: fixture.candidate_thresholds.projection_px,
    },
    source_refs: fixture.source_refs,
  };
}
