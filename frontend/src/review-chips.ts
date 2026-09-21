import { ApiError, api, type Schema } from "./api";

export type Observation = Schema<"ObservationView">;
export type ItemInput = Schema<"InventoryItemCreate">;
export type Decision = Schema<"ObservationAcceptRequest">;
export const REVIEW_LIMIT = 500;

export type ManualChip = { id: string; item: ItemInput };
export type ReviewDraft = {
  removed: ReadonlySet<string>;
  decisions: ReadonlyMap<string, Decision>;
  manual: ManualChip[];
  settled: ReadonlySet<string>;
};

// A submission owns a deep copy, never live draft data.
// The schema also has anyOf branches enforcing a non-empty array. Select its
// full required-field shape; the server validates the non-empty constraint.
export type ReviewPayload = Extract<
  Schema<"ObservationReviewRequest">,
  { accept: unknown }
>;
export type ReviewSubmission = {
  key: string;
  body: ReviewPayload;
  observations: Observation[];
  manualIds: string[];
};

export function emptyDraft(): ReviewDraft {
  return {
    removed: new Set(),
    decisions: new Map(),
    manual: [],
    settled: new Set(),
  };
}

export type DraftAction =
  | { type: "remove"; id: string }
  | { type: "restore" }
  | { type: "decide"; id: string; decision: Decision }
  | { type: "add"; chip: ManualChip }
  | { type: "edit-manual"; id: string; item: ItemInput }
  | { type: "remove-manual"; id: string }
  | { type: "committed"; submission: ReviewSubmission };

export function reviewDraft(
  state: ReviewDraft,
  action: DraftAction,
): ReviewDraft {
  switch (action.type) {
    case "remove":
      return { ...state, removed: new Set([...state.removed, action.id]) };
    case "restore":
      return { ...state, removed: new Set() };
    case "decide":
      return {
        ...state,
        decisions: new Map(state.decisions).set(action.id, action.decision),
      };
    case "add":
      return { ...state, manual: [...state.manual, action.chip] };
    case "edit-manual":
      return {
        ...state,
        manual: state.manual.map((chip) =>
          chip.id === action.id ? { ...chip, item: action.item } : chip,
        ),
      };
    case "remove-manual":
      return {
        ...state,
        manual: state.manual.filter((chip) => chip.id !== action.id),
      };
    case "committed": {
      const ids = new Set([
        ...action.submission.body.accept.map((entry) => entry.observation_id),
        ...action.submission.body.reject,
      ]);
      const manualIds = new Set(action.submission.manualIds);
      return {
        removed: new Set([...state.removed].filter((id) => !ids.has(id))),
        decisions: new Map([...state.decisions].filter(([id]) => !ids.has(id))),
        manual: state.manual.filter((chip) => !manualIds.has(chip.id)),
        // Suppress old query responses, including requests started before save.
        settled: new Set([...state.settled, ...ids]),
      };
    }
  }
}

export function pendingChips(observations: Observation[], draft: ReviewDraft) {
  const seen = new Set<string>();
  return observations.filter((observation) => {
    if (
      observation.decision !== "pending" ||
      draft.settled.has(observation.id) ||
      seen.has(observation.id)
    )
      return false;
    seen.add(observation.id);
    return true;
  });
}

export function suggestionItem(observation: Observation): ItemInput {
  return {
    name: observation.proposed_name,
    quantity: observation.proposed_quantity,
    unit: observation.proposed_unit,
    notes_markdown: "",
  };
}

export function chipDecision(
  observation: Observation,
  draft: ReviewDraft,
): Decision {
  return (
    draft.decisions.get(observation.id) ?? {
      mode: "create",
      item: suggestionItem(observation),
    }
  );
}

export function makeSubmission(
  observations: Observation[],
  draft: ReviewDraft,
  key: string,
): ReviewSubmission {
  const selected = pendingChips(observations, draft);
  const count = selected.length + draft.manual.length;
  if (count === 0 || count > REVIEW_LIMIT)
    throw new Error(`Review between 1 and ${REVIEW_LIMIT} items at a time.`);
  return structuredClone({
    key,
    body: {
      accept: selected
        .filter((observation) => !draft.removed.has(observation.id))
        .map((observation) => ({
          observation_id: observation.id,
          decision: chipDecision(observation, draft),
        })),
      reject: selected
        .filter((observation) => draft.removed.has(observation.id))
        .map((observation) => observation.id),
      add: draft.manual.map((chip) => chip.item),
    },
    observations: selected,
    manualIds: draft.manual.map((chip) => chip.id),
  });
}

// A lost connection, unreadable response, or server failure can follow a commit.
// These must replay the frozen body/key; a definitive 4xx allows a fresh draft.
export function uncertainOutcome(error: unknown) {
  return (
    !(error instanceof ApiError) ||
    error.status === 0 ||
    error.status >= 500 ||
    error.status === 408
  );
}

// Photo status and the review editor must observe the same server-backed set.
export function pendingChipsQuery(code: string) {
  return {
    queryKey: ["observations", code],
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      loadPendingChips(code, signal),
    refetchInterval: 5000,
  };
}

export function pendingCountsByPhoto(observations: Observation[]) {
  const counts = new Map<string, number>();
  for (const observation of pendingChips(observations, emptyDraft())) {
    counts.set(
      observation.image_id,
      (counts.get(observation.image_id) ?? 0) + 1,
    );
  }
  return counts;
}

export async function loadPendingChips(code: string, signal?: AbortSignal) {
  const observations: Observation[] = [];
  const visited = new Set<string>();
  let cursor: string | null | undefined = "";
  do {
    const page: Schema<"ObservationPage"> = await api(
      `/boxes/${encodeURIComponent(code)}/observations?decision=pending&limit=100` +
        (cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""),
      { signal },
    );
    observations.push(...page.items);
    cursor = page.page.next_cursor;
    if (cursor && visited.has(cursor))
      throw new Error("Suggestions could not finish loading. Please retry.");
    if (cursor) visited.add(cursor);
  } while (cursor);
  // Publish only a complete page traversal, never a partly loaded draft.
  return pendingChips(observations, emptyDraft());
}
