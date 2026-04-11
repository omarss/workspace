export {
  findNodeById,
  parseQuery,
  queryBestMatch,
  queryNodes,
} from "./selector-engine.js";
export type { QueryMatch } from "./selector-engine.js";
export {
  findByGeometry,
  findNearest,
  parseGeometryQuery,
} from "./geometry.js";
export type { GeometryMatch, GeometryQuery, SpatialRelation } from "./geometry.js";
