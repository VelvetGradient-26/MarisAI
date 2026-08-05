/** The section registry — what makes a metric page generate itself.
 *
 * A metric page is not written per variable. It is composed from this ordered
 * list, and each entry declares what it *needs* rather than which variables it
 * applies to. `MetricIntelligencePage` walks the list, asks each entry whether
 * the current variable satisfies it, and renders those that do.
 *
 * That indirection is the whole "future ready" requirement. Adding turbidity
 * tomorrow means adding a block to `backend/forecasting/config/forecasting.yaml`
 * and training it; the variable then appears in `/api/v1/forecast/catalog`, and
 * every section whose requirement it meets renders for it. No file in this
 * directory is touched.
 *
 * The requirements are deliberately about *capability*, not identity. There is
 * no list of variable names anywhere in this feature, and adding one would be
 * the thing that breaks the property.
 */

import type { ComponentType } from 'react';
import type { CatalogVariable } from './api/types';

export interface SectionProps {
  variable: CatalogVariable;
  latitude: number;
  longitude: number;
}

/** What a section needs in order to have anything true to show. */
export type Requirement =
  /** Always renderable — needs only the variable's own history. */
  | 'history'
  /** Needs at least one trained forecasting model. */
  | 'forecast'
  /** Needs a trained model *and* its stored SHAP importance. */
  | 'explainability';

export interface SectionDescriptor {
  id: string;
  /** Anchor label, used by the in-page navigation rail. */
  title: string;
  requires: Requirement;
  component: ComponentType<SectionProps>;
  /** Sections above the fold render eagerly; the rest mount on scroll. */
  eager?: boolean;
  /** Approximate rendered height, reserved so lazy mounting does not jump. */
  minHeight?: number;
}

export function satisfies(requirement: Requirement, variable: CatalogVariable): boolean {
  switch (requirement) {
    case 'history':
      // Every catalog entry is, by construction, a variable the download
      // registry can fetch — so history always exists.
      return true;
    case 'forecast':
    case 'explainability':
      return variable.trained_horizons.length > 0;
    default:
      return false;
  }
}

/**
 * Why a section is absent, in the platform's usual register: state the reason,
 * do not silently omit. Returned to the page so it can render a single honest
 * line under the navigation rather than leaving a mystery gap.
 */
export function absenceReason(
  requirement: Requirement,
  variable: CatalogVariable
): string | null {
  if (satisfies(requirement, variable)) return null;
  if (requirement === 'forecast' || requirement === 'explainability') {
    return (
      variable.unavailable_reason ??
      `No forecasting model has been trained for ${variable.label} yet.`
    );
  }
  return null;
}
