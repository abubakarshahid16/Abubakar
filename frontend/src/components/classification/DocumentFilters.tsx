/**
 * Filter the Documents list by role, discipline, equipment type and project.
 *
 * THE FILTERING HAPPENS ON THE SERVER, and this component only chooses what to
 * ask for. Every selection is passed to `GET /api/documents`, which routes it
 * through `classification.restrict` - the one place a filter is intersected
 * with the caller's grants, returning a NARROWER AccessScope. Filtering the
 * returned array here instead would mean the server had already sent rows the
 * caller was not meant to see, and the filter would be decoration over a leak.
 *
 * The axes AND together: choosing a role and a project means "documents that
 * are both", never "either". An OR would widen the result the more the reader
 * narrowed it.
 *
 * A filter that matches nothing shows NOTHING, not everything. The caller
 * asked for company standards; an empty list is the honest answer and falling
 * back to the whole corpus would hand them what they excluded.
 */
import type { DocumentRole } from "../../types/api";

import { ROLE_OPTIONS } from "./MetadataEditor";

export interface DocumentFilterState {
  document_role: DocumentRole[];
  discipline: string[];
  equipment_type: string[];
  project: string[];
}

export const EMPTY_FILTERS: DocumentFilterState = {
  document_role: [], discipline: [], equipment_type: [], project: [],
};

export function hasAnyFilter(f: DocumentFilterState): boolean {
  return (
    f.document_role.length > 0 || f.discipline.length > 0 ||
    f.equipment_type.length > 0 || f.project.length > 0
  );
}

export interface DocumentFiltersProps {
  value: DocumentFilterState;
  onChange: (next: DocumentFilterState) => void;
  /** Values observed in the corpus, for the free-text axes. These are only
   *  suggestions - the reader may type one that currently matches nothing,
   *  and gets an empty list, which is correct. */
  disciplines?: string[];
  equipmentTypes?: string[];
  projects?: string[];
}

function toggle<T extends string>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export function DocumentFilters({
  value, onChange, disciplines = [], equipmentTypes = [], projects = [],
}: DocumentFiltersProps) {
  return (
    <section aria-label="Document filters" className="flex flex-col gap-2">
      <div role="group" aria-label="Document role" className="flex flex-wrap gap-1">
        {ROLE_OPTIONS.map((option) => {
          const on = value.document_role.includes(option.value);
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={on}
              onClick={() =>
                onChange({ ...value, document_role: toggle(value.document_role, option.value) })
              }
              className={`rounded px-2 py-1 text-xs ${on ? "bg-white/20" : "bg-white/5"}`}
            >
              {option.label}
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap gap-2">
        <SelectAxis
          label="Discipline" options={disciplines} selected={value.discipline}
          onPick={(v) => onChange({ ...value, discipline: v })}
        />
        <SelectAxis
          label="Equipment type" options={equipmentTypes} selected={value.equipment_type}
          onPick={(v) => onChange({ ...value, equipment_type: v })}
        />
        <SelectAxis
          label="Project" options={projects} selected={value.project}
          onPick={(v) => onChange({ ...value, project: v })}
        />
        {hasAnyFilter(value) && (
          <button
            type="button"
            onClick={() => onChange(EMPTY_FILTERS)}
            className="self-end rounded px-2 py-1 text-xs underline opacity-80"
          >
            Clear filters
          </button>
        )}
      </div>
    </section>
  );
}

function SelectAxis({
  label, options, selected, onPick,
}: {
  label: string;
  options: string[];
  selected: string[];
  onPick: (next: string[]) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="opacity-80">{label}</span>
      <select
        aria-label={label}
        value={selected[0] ?? ""}
        onChange={(e) => onPick(e.target.value === "" ? [] : [e.target.value])}
        className="rounded border border-white/15 bg-transparent px-2 py-1"
      >
        {/* "Any" is the absence of a filter on this axis, not a value. */}
        <option value="">Any</option>
        {options.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
    </label>
  );
}
