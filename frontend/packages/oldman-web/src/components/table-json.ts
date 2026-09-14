import {
  columnFilteringFeature,
  constructTable,
  globalFilteringFeature,
  rowPaginationFeature,
  rowSelectionFeature,
  rowSortingFeature,
  tableFeatures,
  type ColumnDef,
  type Table
} from "@tanstack/table-core";
import { storeReactivityBindings } from "@tanstack/table-core/store-reactivity-bindings";

export type TableJsonRawValue = string | number | boolean | null;

export interface TableJsonColumn {
  label: string;
  name: string;
  searchable: boolean;
  sortable: boolean;
  type: string;
}

export interface TableJsonRow {
  cells: Record<string, string | null>;
  data: Record<string, unknown>;
  raw_values: Record<string, TableJsonRawValue>;
}

export interface TableJsonPayload {
  columns: TableJsonColumn[];
  pagination: {
    filtered_total: number;
    has_next: boolean;
    page: number;
    page_size: number;
    total: number;
  };
  rows: TableJsonRow[];
  sort: string;
}

export interface JsonTableState {
  page: number;
  pageSize: number;
  search: string;
  sort: { descending: boolean; key: string } | null;
}

const jsonTableFeatures = tableFeatures({
  coreReactivityFeature: storeReactivityBindings(),
  columnFilteringFeature,
  globalFilteringFeature,
  rowSortingFeature,
  rowPaginationFeature,
  rowSelectionFeature
});

type TanStackJsonTable = Table<typeof jsonTableFeatures, TableJsonRow>;

/**
 * 校验 Table endpoint 的受信 JSON 边界，避免错误 payload 生成半残 DOM。
 */
export function parseTableJsonPayload(value: unknown, expectedColumns: readonly string[], selectable: boolean): TableJsonPayload {
  const payload = requireRecord(value, "Table JSON payload");
  const columns = requireArray(payload.columns, "Table JSON columns");
  const rows = requireArray(payload.rows, "Table JSON rows");
  const pagination = requireRecord(payload.pagination, "Table JSON pagination");

  const parsedColumns = columns.map((column, index) => parseColumn(column, index));
  const columnNames = parsedColumns.map((column) => column.name);
  if (new Set(columnNames).size !== columnNames.length) {
    throw new Error("Table JSON columns must be unique");
  }
  if (columnNames.length !== expectedColumns.length || columnNames.some((name, index) => name !== expectedColumns[index])) {
    throw new Error("Table JSON columns do not match the rendered table shell");
  }

  const parsedRows = rows.map((row, index) => parseRow(row, index, columnNames));
  const page = requirePositiveInteger(pagination.page, "pagination.page");
  const pageSize = requirePositiveInteger(pagination.page_size, "pagination.page_size");
  const total = requireNonNegativeInteger(pagination.total, "pagination.total");
  const filteredTotal = requireNonNegativeInteger(pagination.filtered_total, "pagination.filtered_total");
  const hasNext = requireBoolean(pagination.has_next, "pagination.has_next");
  const sort = requireString(payload.sort, "Table JSON sort");

  return {
    columns: parsedColumns,
    pagination: {
      filtered_total: filteredTotal,
      has_next: hasNext,
      page,
      page_size: pageSize,
      total
    },
    rows: parsedRows,
    sort
  };
}

/** TanStack 只管理当前服务器页的 row model 和选择状态。 */
export class JsonTableModel {
  private table: TanStackJsonTable | null = null;

  update(payload: TableJsonPayload, state: JsonTableState, selectable: boolean): TableJsonRow[] {
    if (!this.table) {
      this.table = constructTable({
        features: jsonTableFeatures,
        columns: createColumns(payload.columns),
        data: payload.rows,
        enableMultiSort: false,
        enableRowRangeSelection: false,
        enableRowSelection: selectable,
        getRowId: (row, index) => rowIdentifier(row) ?? String(index),
        manualFiltering: true,
        manualPagination: true,
        manualSorting: true,
        rowCount: payload.pagination.filtered_total,
        state: tableState(state)
      });
    } else {
      this.table.setOptions((options) => ({
        ...options,
        data: payload.rows,
        enableRowSelection: selectable,
        rowCount: payload.pagination.filtered_total,
        state: tableState(state)
      }));
    }

    this.table.resetRowSelection(true);
    return this.table.getRowModel().rows.map((row) => row.original);
  }

  setRowSelected(rowId: string, selected: boolean): void {
    this.table?.getRow(rowId).toggleSelected(selected);
  }

  setAllRowsSelected(selected: boolean): void {
    this.table?.toggleAllRowsSelected(selected, { deselectAll: !selected });
  }
}

function createColumns(columns: readonly TableJsonColumn[]): Array<ColumnDef<typeof jsonTableFeatures, TableJsonRow>> {
  return columns.map((column) => ({
    accessorFn: (row) => row.raw_values[column.name],
    enableGlobalFilter: column.searchable,
    enableSorting: column.sortable,
    header: column.label,
    id: column.name
  }));
}

function tableState(state: JsonTableState) {
  return {
    globalFilter: state.search,
    pagination: { pageIndex: state.page - 1, pageSize: state.pageSize },
    sorting: state.sort ? [{ desc: state.sort.descending, id: state.sort.key }] : []
  };
}

function parseColumn(value: unknown, index: number): TableJsonColumn {
  const column = requireRecord(value, `Table JSON column ${index}`);
  const name = requireString(column.name, `columns[${index}].name`);
  if (!name) throw new Error(`columns[${index}].name must not be empty`);
  return {
    label: requireString(column.label, `columns[${index}].label`),
    name,
    searchable: requireBoolean(column.searchable, `columns[${index}].searchable`),
    sortable: requireBoolean(column.sortable, `columns[${index}].sortable`),
    type: requireString(column.type, `columns[${index}].type`)
  };
}

function parseRow(value: unknown, index: number, columns: readonly string[]): TableJsonRow {
  const row = requireRecord(value, `Table JSON row ${index}`);
  const cells = requireRecord(row.cells, `rows[${index}].cells`);
  const rawValues = requireRecord(row.raw_values, `rows[${index}].raw_values`);
  const data = requireRecord(row.data, `rows[${index}].data`);

  for (const column of columns) {
    if (!Object.hasOwn(cells, column) || !isCellValue(cells[column])) {
      throw new Error(`rows[${index}].cells.${column} must be a string or null`);
    }
    if (!Object.hasOwn(rawValues, column) || !isRawValue(rawValues[column])) {
      throw new Error(`rows[${index}].raw_values.${column} must be a scalar or null`);
    }
  }
  if (rowIdentifier({ data } as TableJsonRow) === null) {
    throw new Error(`rows[${index}].data.id must be a string or number`);
  }

  return {
    cells: cells as Record<string, string | null>,
    data,
    raw_values: rawValues as Record<string, TableJsonRawValue>
  };
}

function rowIdentifier(row: TableJsonRow): string | null {
  const id = row.data.id;
  return typeof id === "string" || (typeof id === "number" && Number.isFinite(id)) ? String(id) : null;
}

function requireRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${label} must be an object`);
  return value as Record<string, unknown>;
}

function requireArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  return value;
}

function requireString(value: unknown, label: string): string {
  if (typeof value !== "string") throw new Error(`${label} must be a string`);
  return value;
}

function requireBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${label} must be a boolean`);
  return value;
}

function requirePositiveInteger(value: unknown, label: string): number {
  if (!Number.isInteger(value) || Number(value) <= 0) throw new Error(`${label} must be a positive integer`);
  return Number(value);
}

function requireNonNegativeInteger(value: unknown, label: string): number {
  if (!Number.isInteger(value) || Number(value) < 0) throw new Error(`${label} must be a non-negative integer`);
  return Number(value);
}

function isCellValue(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isRawValue(value: unknown): value is TableJsonRawValue {
  return value === null || typeof value === "string" || typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value));
}
