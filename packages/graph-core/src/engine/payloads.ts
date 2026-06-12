import { z } from "zod";
import type { JournalOp } from "../domain/journal.js";

/** Typed payload schemas for each JournalOp. The applier validates against
 *  these on the way in and on replay, so a bad payload fails loudly at the
 *  application boundary without polluting the persisted wire format. */

export const mergeNodesPayload = z.object({
  survivorId: z.string(),
  absorbedIds: z.array(z.string()),
  reason: z.string().nullish(),
  /** Self-describing merge provenance: absorbed nodes are dropped, so
   *  their names are recorded here for the merge-pattern learner. */
  survivorName: z.string().nullish(),
  absorbedNames: z.array(z.string()).default([]),
  entityType: z.string().nullish(),
  /** Optional rename of the survivor as part of the merge (atomic undo). */
  newName: z.string().nullish(),
});

export const splitNodePayload = z.object({
  originalId: z.string(),
  /** Each becomes a Node (must carry layer/type/granularity/name). */
  newNodes: z.array(z.record(z.unknown())),
  /** edgeId → which new node inherits each incident edge. Missing → first. */
  edgeRedirect: z.record(z.string()).default({}),
});

export const retypeNodePayload = z.object({
  nodeId: z.string(),
  newType: z.string(),
  oldType: z.string().nullish(),
});

export const moveToCommunityPayload = z.object({
  nodeId: z.string(),
  toCommunityId: z.string(),
  fromCommunityId: z.string().nullish(),
});

export const editEdgePayload = z.object({
  edgeId: z.string(),
  updates: z.record(z.unknown()),
});

export const deleteEdgePayload = z.object({
  edgeId: z.string(),
  /** When given, switches to SOFT delete: the edge stays with txTo +
   *  invalidation stamped (revert-eligible). Absent → hard delete. */
  reason: z.string().nullish(),
  ingestionEventId: z.string().nullish(),
  /** txTo / invalidation.at instant for the soft delete; falls back to the
   *  entry timestamp. */
  supersededAt: z.string().nullish(),
});

export const deleteNodePayload = z.object({
  nodeId: z.string(),
  reason: z.string().nullish(),
});

export const addEdgePayload = z.object({
  edge: z.record(z.unknown()),
});

export const setSummaryPayload = z.object({
  nodeId: z.string(),
  summary: z.string().nullable(),
});

export const updateNodeNamePayload = z.object({
  nodeId: z.string(),
  name: z.string(),
});

export const OP_SCHEMAS = {
  merge_nodes: mergeNodesPayload,
  split_node: splitNodePayload,
  retype_node: retypeNodePayload,
  move_to_community: moveToCommunityPayload,
  edit_edge: editEdgePayload,
  delete_edge: deleteEdgePayload,
  delete_node: deleteNodePayload,
  add_edge: addEdgePayload,
  set_summary: setSummaryPayload,
  update_node_name: updateNodeNamePayload,
} as const satisfies Record<JournalOp, z.ZodType>;

export type PayloadOf<O extends JournalOp> = z.infer<(typeof OP_SCHEMAS)[O]>;

/** Inflate + validate a wire-format payload for an op. Throws on mismatch. */
export function parsePayload<O extends JournalOp>(
  op: O,
  payload: unknown,
): PayloadOf<O> {
  return OP_SCHEMAS[op].parse(payload) as PayloadOf<O>;
}
