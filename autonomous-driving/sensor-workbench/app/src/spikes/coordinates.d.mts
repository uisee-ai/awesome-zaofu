export type Point2 = readonly [number, number];
export type Point3 = readonly [number, number, number];
export type Matrix3 = readonly [Point3, Point3, Point3];
export type Matrix4 = readonly [
  readonly [number, number, number, number],
  readonly [number, number, number, number],
  readonly [number, number, number, number],
  readonly [number, number, number, number],
];

export interface NuScenesTransforms {
  readonly lidar_to_ego: Matrix4;
  readonly ego_to_global_at_lidar: Matrix4;
  readonly global_to_ego_at_camera: Matrix4;
  readonly ego_to_camera: Matrix4;
}

export interface CameraProjection {
  readonly pixel: Point2;
  readonly depth: number;
}

export function transformNuScenesLidarToCamera(point: Point3, transforms: NuScenesTransforms): Point3;
export function openLaneWaymoToStandardCamera(point: Point3, waymoToStandardCamera: Matrix3): Point3;
export function projectCameraPoint(point: Point3, cameraIntrinsic: Matrix3): CameraProjection | null;
export function measureCoordinateFixture(fixture: Readonly<Record<string, any>>, fixtureSha256: string): Readonly<Record<string, any>>;
