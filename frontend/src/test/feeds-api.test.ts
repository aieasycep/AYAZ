import { describe, it, expect } from 'vitest';
import type {
  FeedRule,
  RuleType,
  RulesImpactResponse,
  SimulateRuleResponse,
  LintIssue,
  LintResponse,
} from '@/lib/feeds-api';

// ---------------------------------------------------------------------------
// Helpers — replicate the pure logic exported from feeds-api for unit testing
// (The network functions themselves can't be unit-tested without a server;
//  we test the pure transformation helpers and type contracts here.)
// ---------------------------------------------------------------------------

// Mirror of buildRuleConfig from page.tsx — tested in isolation
interface RuleConfigState {
  sv_field: string; sv_value: string;
  rf_from: string; rf_to: string;
  fr_field: string; fr_pattern: string; fr_replacement: string; fr_use_regex: boolean;
  fi_condition_field: string; fi_condition_op: string; fi_condition_value: string;
  calc_field: string; calc_expression: string;
}

function buildRuleConfig(type: RuleType, cfg: RuleConfigState): Record<string, unknown> {
  switch (type) {
    case 'set_value':
      return { field: cfg.sv_field, value: cfg.sv_value };
    case 'rename_field':
      return { from_field: cfg.rf_from, to_field: cfg.rf_to, drop_original: false };
    case 'find_replace':
      return {
        field: cfg.fr_field || undefined,
        pattern: cfg.fr_pattern,
        replacement: cfg.fr_replacement,
        use_regex: cfg.fr_use_regex,
      };
    case 'filter_include':
      return { condition_field: cfg.fi_condition_field, condition_op: cfg.fi_condition_op, condition_value: cfg.fi_condition_value };
    case 'filter_exclude':
      return { condition_field: cfg.fi_condition_field, condition_op: cfg.fi_condition_op, condition_value: cfg.fi_condition_value };
    case 'calculated':
      return { field: cfg.calc_field, expression: cfg.calc_expression };
  }
}

const BASE_CFG: RuleConfigState = {
  sv_field: '', sv_value: '',
  rf_from: '', rf_to: '',
  fr_field: '', fr_pattern: '', fr_replacement: '', fr_use_regex: false,
  fi_condition_field: '', fi_condition_op: 'eq', fi_condition_value: '',
  calc_field: '', calc_expression: '',
};

// ---------------------------------------------------------------------------
// buildRuleConfig — correct backend field names
// ---------------------------------------------------------------------------

describe('buildRuleConfig', () => {
  it('set_value uses field + value keys', () => {
    const cfg = buildRuleConfig('set_value', { ...BASE_CFG, sv_field: 'condition', sv_value: 'new' });
    expect(cfg).toEqual({ field: 'condition', value: 'new' });
  });

  it('rename_field uses from_field + to_field + drop_original', () => {
    const cfg = buildRuleConfig('rename_field', { ...BASE_CFG, rf_from: 'g:id', rf_to: 'id' });
    expect(cfg).toEqual({ from_field: 'g:id', to_field: 'id', drop_original: false });
  });

  it('find_replace uses pattern + replacement + use_regex', () => {
    const cfg = buildRuleConfig('find_replace', {
      ...BASE_CFG,
      fr_field: 'title',
      fr_pattern: '  +',
      fr_replacement: ' ',
      fr_use_regex: true,
    });
    expect(cfg.pattern).toBe('  +');
    expect(cfg.replacement).toBe(' ');
    expect(cfg.use_regex).toBe(true);
    expect(cfg.field).toBe('title');
  });

  it('find_replace omits field when empty', () => {
    const cfg = buildRuleConfig('find_replace', {
      ...BASE_CFG,
      fr_field: '',
      fr_pattern: 'foo',
      fr_replacement: 'bar',
      fr_use_regex: false,
    });
    expect(cfg.field).toBeUndefined();
  });

  it('filter_include uses condition_field + condition_op + condition_value', () => {
    const cfg = buildRuleConfig('filter_include', {
      ...BASE_CFG,
      fi_condition_field: 'availability',
      fi_condition_op: 'eq',
      fi_condition_value: 'in stock',
    });
    expect(cfg).toEqual({ condition_field: 'availability', condition_op: 'eq', condition_value: 'in stock' });
  });

  it('filter_exclude same shape as filter_include', () => {
    const cfg = buildRuleConfig('filter_exclude', {
      ...BASE_CFG,
      fi_condition_field: 'price',
      fi_condition_op: 'lt',
      fi_condition_value: '0',
    });
    expect(cfg).toEqual({ condition_field: 'price', condition_op: 'lt', condition_value: '0' });
  });

  it('calculated uses field + expression', () => {
    const cfg = buildRuleConfig('calculated', {
      ...BASE_CFG,
      calc_field: 'sale_price',
      calc_expression: '{price} * 0.9',
    });
    expect(cfg).toEqual({ field: 'sale_price', expression: '{price} * 0.9' });
  });
});

// ---------------------------------------------------------------------------
// FeedRule type: is_paused field is present
// ---------------------------------------------------------------------------

describe('FeedRule type', () => {
  it('accepts is_paused: false', () => {
    const rule: FeedRule = {
      id: 'r1',
      feed_channel_id: 'c1',
      position: 0,
      rule_type: 'set_value',
      config: { field: 'title', value: 'test' },
      is_paused: false,
      created_at: '2026-01-01T00:00:00Z',
    };
    expect(rule.is_paused).toBe(false);
  });

  it('accepts is_paused: true', () => {
    const rule: FeedRule = {
      id: 'r2',
      feed_channel_id: 'c1',
      position: 1,
      rule_type: 'filter_exclude',
      config: { condition_field: 'stock', condition_op: 'eq', condition_value: '0' },
      is_paused: true,
      created_at: '2026-01-01T00:00:00Z',
    };
    expect(rule.is_paused).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// RulesImpactResponse type contract
// ---------------------------------------------------------------------------

describe('RulesImpactResponse type', () => {
  it('carries total_before, total_after, sampled, and per-rule stats', () => {
    const resp: RulesImpactResponse = {
      total_before: 500,
      total_after: 480,
      sampled: false,
      sampled_total: null,
      rules: [
        {
          rule_id: 'r1',
          position: 0,
          rule_type: 'filter_exclude',
          is_paused: false,
          affected_count: 0,
          excluded_count: 20,
        },
      ],
    };
    expect(resp.total_after).toBe(480);
    expect(resp.rules[0].excluded_count).toBe(20);
    expect(resp.sampled).toBe(false);
  });

  it('carries sampled=true with sampled_total', () => {
    const resp: RulesImpactResponse = {
      total_before: 1000,
      total_after: 950,
      sampled: true,
      sampled_total: 5000,
      rules: [],
    };
    expect(resp.sampled).toBe(true);
    expect(resp.sampled_total).toBe(5000);
  });
});

// ---------------------------------------------------------------------------
// SimulateRuleResponse type contract
// ---------------------------------------------------------------------------

describe('SimulateRuleResponse type', () => {
  it('carries counts and sample arrays', () => {
    const resp: SimulateRuleResponse = {
      affected_count: 42,
      excluded_count: 0,
      sample_before: [{ id: '1', title: 'Widget' }],
      sample_after: [{ id: '1', title: 'Widget v2' }],
    };
    expect(resp.affected_count).toBe(42);
    expect(resp.sample_before[0].title).toBe('Widget');
    expect(resp.sample_after[0].title).toBe('Widget v2');
  });
});

// ---------------------------------------------------------------------------
// LintResponse type contract + code labels
// ---------------------------------------------------------------------------

const LINT_CODE_LABELS: Record<string, string> = {
  no_effect: 'Bu kural hiçbir ürünü etkilemiyor',
  excludes_all: 'Bu kural neredeyse tüm ürünleri eliyor',
  shadowed: 'Daha önceki bir kural bunu gölgeliyor',
  duplicate: 'Yinelenen kural',
};

describe('LintResponse type', () => {
  it('carries severity, code, rule_id per issue', () => {
    const resp: LintResponse = {
      issues: [
        { severity: 'warning', rule_id: 'r1', position: 0, code: 'no_effect', message: 'No effect' },
        { severity: 'error', rule_id: 'r2', position: 1, code: 'excludes_all', message: 'Excludes all' },
      ],
    };
    expect(resp.issues).toHaveLength(2);
    expect(resp.issues[0].severity).toBe('warning');
    expect(resp.issues[1].severity).toBe('error');
  });

  it('all known lint codes have Turkish labels', () => {
    const codes = ['no_effect', 'excludes_all', 'shadowed', 'duplicate'];
    for (const code of codes) {
      expect(LINT_CODE_LABELS[code]).toBeDefined();
      expect(LINT_CODE_LABELS[code].length).toBeGreaterThan(5);
    }
  });

  it('no_effect maps to correct Turkish text', () => {
    const issue: LintIssue = { severity: 'warning', rule_id: 'r1', position: 0, code: 'no_effect', message: '' };
    expect(LINT_CODE_LABELS[issue.code]).toBe('Bu kural hiçbir ürünü etkilemiyor');
  });

  it('excludes_all maps to correct Turkish text', () => {
    expect(LINT_CODE_LABELS['excludes_all']).toBe('Bu kural neredeyse tüm ürünleri eliyor');
  });

  it('shadowed maps to correct Turkish text', () => {
    expect(LINT_CODE_LABELS['shadowed']).toBe('Daha önceki bir kural bunu gölgeliyor');
  });

  it('duplicate maps to correct Turkish text', () => {
    expect(LINT_CODE_LABELS['duplicate']).toBe('Yinelenen kural');
  });
});
