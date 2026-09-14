export type FloatingPlacement =
  | "top"
  | "top-start"
  | "top-end"
  | "right"
  | "bottom"
  | "bottom-start"
  | "bottom-end"
  | "left";

export interface FloatingPositionOptions {
  gap?: number;
  margin?: number;
  preserveWidth?: boolean;
}

const PLACEMENTS: ReadonlySet<string> = new Set([
  "top",
  "top-start",
  "top-end",
  "right",
  "bottom",
  "left",
  "bottom-start",
  "bottom-end"
]);

/** Parse a declarative placement while keeping component defaults explicit. */
export function floatingPlacement(value: string | undefined, fallback: FloatingPlacement): FloatingPlacement {
  return value && PLACEMENTS.has(value) ? (value as FloatingPlacement) : fallback;
}

/** Position a fixed floating surface, flipping and clamping it inside the viewport. */
export function positionFloatingElement(
  reference: HTMLElement,
  floating: HTMLElement,
  placement: FloatingPlacement,
  options: FloatingPositionOptions = {}
): FloatingPlacement {
  const gap = options.gap ?? 8;
  const margin = options.margin ?? 8;
  const referenceRect = reference.getBoundingClientRect();
  const floatingRect = floating.getBoundingClientRect();
  const width = Math.min(floatingRect.width || floating.offsetWidth, Math.max(0, window.innerWidth - margin * 2));
  const height = floatingRect.height || floating.offsetHeight;
  const effectivePlacement = flipPlacement(placement, referenceRect, width, height, gap, margin);
  const coordinates = placementCoordinates(effectivePlacement, referenceRect, width, height, gap);
  const left = clamp(coordinates.left, margin, Math.max(margin, window.innerWidth - width - margin));
  const top = clamp(coordinates.top, margin, Math.max(margin, window.innerHeight - height - margin));

  floating.style.position = "fixed";
  floating.style.left = `${left}px`;
  floating.style.right = "auto";
  floating.style.top = `${top}px`;
  floating.style.maxWidth = `calc(100vw - ${margin * 2}px)`;
  if (options.preserveWidth) floating.style.width = `${width}px`;

  const availableHeight = Math.max(0, window.innerHeight - margin * 2);
  if (height > availableHeight) {
    floating.style.maxHeight = `calc(100vh - ${margin * 2}px)`;
    floating.style.overflowY = "auto";
  } else {
    floating.style.removeProperty("maxHeight");
    floating.style.removeProperty("overflowY");
  }

  floating.dataset.omEffectivePlacement = effectivePlacement;
  return effectivePlacement;
}

/** Return a floating surface to stylesheet-controlled positioning. */
export function resetFloatingPosition(floating: HTMLElement): void {
  for (const property of ["position", "left", "right", "top", "width", "maxWidth", "maxHeight", "overflowY"]) {
    floating.style.removeProperty(property);
  }
  delete floating.dataset.omEffectivePlacement;
}

function flipPlacement(
  placement: FloatingPlacement,
  reference: DOMRect,
  width: number,
  height: number,
  gap: number,
  margin: number
): FloatingPlacement {
  const side = placementSide(placement);
  const required = (side === "top" || side === "bottom" ? height : width) + gap;
  const available = {
    top: reference.top - margin,
    right: window.innerWidth - reference.right - margin,
    bottom: window.innerHeight - reference.bottom - margin,
    left: reference.left - margin
  };
  const opposite = oppositePlacement(placement);
  const oppositeSide = placementSide(opposite);
  return available[side] < required && available[oppositeSide] > available[side] ? opposite : placement;
}

function placementCoordinates(
  placement: FloatingPlacement,
  reference: DOMRect,
  width: number,
  height: number,
  gap: number
): { left: number; top: number } {
  if (placement === "bottom-start") return { left: reference.left, top: reference.bottom + gap };
  if (placement === "bottom-end") return { left: reference.right - width, top: reference.bottom + gap };
  if (placement === "top-start") return { left: reference.left, top: reference.top - height - gap };
  if (placement === "top-end") return { left: reference.right - width, top: reference.top - height - gap };
  if (placement === "top") return { left: reference.left + (reference.width - width) / 2, top: reference.top - height - gap };
  if (placement === "right") return { left: reference.right + gap, top: reference.top + (reference.height - height) / 2 };
  if (placement === "left") return { left: reference.left - width - gap, top: reference.top + (reference.height - height) / 2 };
  return { left: reference.left + (reference.width - width) / 2, top: reference.bottom + gap };
}

function oppositePlacement(placement: FloatingPlacement): FloatingPlacement {
  if (placement === "top") return "bottom";
  if (placement === "right") return "left";
  if (placement === "left") return "right";
  if (placement === "bottom-end") return "top-end";
  if (placement === "bottom-start") return "top-start";
  if (placement === "top-end") return "bottom-end";
  if (placement === "top-start") return "bottom-start";
  return "top";
}

function placementSide(placement: FloatingPlacement): "top" | "right" | "bottom" | "left" {
  if (placement === "bottom" || placement === "bottom-start" || placement === "bottom-end") return "bottom";
  if (placement === "top" || placement === "top-start" || placement === "top-end") return "top";
  return placement;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}
