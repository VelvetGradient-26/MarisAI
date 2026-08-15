import type { ComponentType } from 'react';

import { DashboardAlerts } from './DashboardAlerts';
import { DashboardCharts } from './DashboardCharts';
import { DashboardMetrics } from './DashboardMetrics';
import { DashboardOverview } from './DashboardOverview';
import { DashboardSources } from './DashboardSources';
import { Data } from './Data';
import { Features } from './Features';
import { ForecastEngine } from './ForecastEngine';
import { ForecastMap } from './ForecastMap';
import { ForecastResults } from './ForecastResults';
import { Fusion } from './Fusion';
import { Hab } from './Hab';
import { Habitat } from './Habitat';
import { Limits } from './Limits';
import { Metrics } from './Metrics';
import { OceanConventions } from './OceanConventions';
import { OceanFields } from './OceanFields';
import { Overview } from './Overview';
import { Primer } from './Primer';
import { Problems } from './Problems';
import { Results } from './Results';
import { Validation } from './Validation';

export interface Chapter {
  /** URL slug — `/docs?c=<id>`. Stable; changing one breaks saved links. */
  id: string;
  /** Sidebar label. Kept short; the <h1> inside the chapter can be longer. */
  label: string;
  /** Browser tab title suffix. */
  title: string;
  group: string;
  Component: ComponentType;
}

/**
 * The chapter list, in reading order. Order here drives the sidebar, the
 * prev/next pager and the mobile picker — there is no second place to update.
 *
 * The ocean-reference groups in PENDING_GROUPS are declared as pending rather
 * than hidden, because the shape of the section is part of what it
 * communicates: this is a reference that is going to keep growing, not a
 * one-off page.
 */
export const CHAPTERS: Chapter[] = [
  {
    id: 'dash-overview',
    label: 'Overview',
    title: 'What the dashboard shows',
    group: 'Ocean intelligence dashboard',
    Component: DashboardOverview,
  },
  {
    id: 'dash-metrics',
    label: 'The six indicators',
    title: 'The six indicators, explained',
    group: 'Ocean intelligence dashboard',
    Component: DashboardMetrics,
  },
  {
    id: 'dash-sources',
    label: 'Sources & satellites',
    title: 'Sources, satellites & instruments',
    group: 'Ocean intelligence dashboard',
    Component: DashboardSources,
  },
  {
    id: 'dash-charts',
    label: 'Charts & coverage',
    title: 'Charts & historical coverage',
    group: 'Ocean intelligence dashboard',
    Component: DashboardCharts,
  },
  {
    id: 'dash-alerts',
    label: 'Alerts & thresholds',
    title: 'Alerts & thresholds',
    group: 'Ocean intelligence dashboard',
    Component: DashboardAlerts,
  },
  {
    id: 'forecast-engine',
    label: 'How it works',
    title: 'One framework, every variable',
    group: 'Forecasting engine',
    Component: ForecastEngine,
  },
  {
    id: 'forecast-results',
    label: 'Skill & the bar',
    title: 'What it actually achieves',
    group: 'Forecasting engine',
    Component: ForecastResults,
  },
  {
    id: 'forecast-map',
    label: 'The forecast map',
    title: 'The same engine, drawn as a map',
    group: 'Forecasting engine',
    Component: ForecastMap,
  },
  {
    id: 'overview',
    label: 'Overview',
    title: 'Overview',
    group: 'Machine learning',
    Component: Overview,
  },
  {
    id: 'primer',
    label: 'ML primer',
    title: 'A primer',
    group: 'Machine learning',
    Component: Primer,
  },
  {
    id: 'problems',
    label: 'The two problems',
    title: 'The two problem statements',
    group: 'Machine learning',
    Component: Problems,
  },
  {
    id: 'data',
    label: 'Data & variables',
    title: 'Every variable, and how we fetched it',
    group: 'Machine learning',
    Component: Data,
  },
  {
    id: 'fusion',
    label: 'The fusion layer',
    title: 'The Marine Data Fusion Layer',
    group: 'Machine learning',
    Component: Fusion,
  },
  {
    id: 'features',
    label: 'Feature engineering',
    title: 'Feature engineering',
    group: 'Machine learning',
    Component: Features,
  },
  {
    id: 'hab',
    label: 'Problem A — HAB',
    title: 'HAB early warning',
    group: 'Machine learning',
    Component: Hab,
  },
  {
    id: 'habitat',
    label: 'Problem B — habitat',
    title: 'Fish habitat / PFZ',
    group: 'Machine learning',
    Component: Habitat,
  },
  {
    id: 'validation',
    label: 'Validation & leakage',
    title: 'Validation & leakage',
    group: 'Machine learning',
    Component: Validation,
  },
  {
    id: 'metrics',
    label: 'Metrics, explained',
    title: 'Metrics, explained',
    group: 'Machine learning',
    Component: Metrics,
  },
  {
    id: 'results',
    label: 'Results',
    title: 'Results',
    group: 'Machine learning',
    Component: Results,
  },
  {
    id: 'limits',
    label: 'Limitations & next',
    title: 'Limitations & what comes next',
    group: 'Machine learning',
    Component: Limits,
  },
  {
    id: 'ocean-fields',
    label: 'The fields',
    title: 'The fields, and where they come from',
    group: 'Ocean & atmosphere',
    Component: OceanFields,
  },
  {
    id: 'ocean-conventions',
    label: 'Directions & colour',
    title: 'Directions, colour & how to read a layer',
    group: 'Ocean & atmosphere',
    Component: OceanConventions,
  },
];

/** Groups that are planned but have no chapters yet. */
export const PENDING_GROUPS: { group: string; entries: string[] }[] = [
  {
    group: 'The ocean',
    entries: ['How the oceans formed', 'Basins, seas & currents', 'Chemistry & the carbon cycle'],
  },
  {
    group: 'Life in the ocean',
    entries: ['Plankton & the food web', 'Fishes', 'Marine mammals & reptiles', 'Reefs & the deep sea'],
  },
];

export const DEFAULT_CHAPTER = CHAPTERS[0].id;

export function findChapter(id: string | null): Chapter {
  return CHAPTERS.find((chapter) => chapter.id === id) ?? CHAPTERS[0];
}

export const CHAPTER_GROUPS: { group: string; chapters: Chapter[] }[] = CHAPTERS.reduce(
  (groups, chapter) => {
    const existing = groups.find((entry) => entry.group === chapter.group);
    if (existing) existing.chapters.push(chapter);
    else groups.push({ group: chapter.group, chapters: [chapter] });
    return groups;
  },
  [] as { group: string; chapters: Chapter[] }[]
);
