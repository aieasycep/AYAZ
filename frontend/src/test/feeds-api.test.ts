import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type {
  FeedRule,
  RuleType,
  RulesImpactResponse,
  SimulateRuleResponse,
  LintIssue,
  LintResponse,
  RuleFromTextResponse,
  FeedQualityResponse,
  QualityIssue,
  EnrichmentSuggestion,
  EnrichSourceResponse,
  ApplyEnrichmentResponse,
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

// ---------------------------------------------------------------------------
// RuleFromTextResponse type contract
// ---------------------------------------------------------------------------

describe('RuleFromTextResponse type', () => {
  it('carries rule_type, config, explanation, confidence=high', () => {
    const resp: RuleFromTextResponse = {
      rule_type: 'filter_exclude',
      config: { condition_field: 'availability', condition_op: 'eq', condition_value: 'out of stock' },
      explanation: 'Stokta olmayan ürünleri hariç tutar.',
      confidence: 'high',
    };
    expect(resp.rule_type).toBe('filter_exclude');
    expect(resp.confidence).toBe('high');
    expect(resp.impact).toBeUndefined();
  });

  it('carries confidence=low', () => {
    const resp: RuleFromTextResponse = {
      rule_type: 'set_value',
      config: { field: 'brand', value: 'Bilinmiyor' },
      explanation: 'Marka alanını varsayılan bir değerle doldurur.',
      confidence: 'low',
    };
    expect(resp.confidence).toBe('low');
  });

  it('carries optional impact when present', () => {
    const resp: RuleFromTextResponse = {
      rule_type: 'filter_exclude',
      config: { condition_field: 'availability', condition_op: 'eq', condition_value: 'out of stock' },
      explanation: 'Stokta olmayan ürünleri hariç tutar.',
      confidence: 'high',
      impact: { affected_count: 120, excluded_count: 45 },
    };
    expect(resp.impact?.affected_count).toBe(120);
    expect(resp.impact?.excluded_count).toBe(45);
  });
});

// ---------------------------------------------------------------------------
// ruleFromText — fetch mock
// ---------------------------------------------------------------------------

describe('ruleFromText', () => {
  beforeEach(() => {
    // Provide localStorage stub in jsdom-less environment
    if (typeof globalThis.localStorage === 'undefined') {
      Object.defineProperty(globalThis, 'localStorage', {
        value: { getItem: () => 'test-token', removeItem: vi.fn(), setItem: vi.fn() },
        writable: true,
      });
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('calls POST /api/v1/feeds/channels/{channelId}/rules/from-text and returns parsed response', async () => {
    const mockResponse: RuleFromTextResponse = {
      rule_type: 'filter_exclude',
      config: { condition_field: 'availability', condition_op: 'eq', condition_value: 'out of stock' },
      explanation: 'Stokta olmayan ürünleri çıkarır.',
      confidence: 'high',
      impact: { affected_count: 80, excluded_count: 30 },
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { ruleFromText } = await import('@/lib/feeds-api');
    const result = await ruleFromText('channel-123', 'stokta olmayan ürünleri çıkar');

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/feeds/channels/channel-123/rules/from-text');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body as string)).toEqual({ text: 'stokta olmayan ürünleri çıkar' });
    expect(result.rule_type).toBe('filter_exclude');
    expect(result.confidence).toBe('high');
    expect(result.impact?.affected_count).toBe(80);
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Sunucu hatası'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { ruleFromText: rft } = await import('@/lib/feeds-api');
    await expect(rft('channel-123', 'test')).rejects.toThrow('Sunucu hatası');
  });
});

// ---------------------------------------------------------------------------
// configToFormState — reverse-mapping (mirrored here for isolation tests)
// ---------------------------------------------------------------------------

interface RuleConfigStateFull {
  sv_field: string; sv_value: string;
  rf_from: string; rf_to: string;
  fr_field: string; fr_pattern: string; fr_replacement: string; fr_use_regex: boolean;
  fi_condition_field: string; fi_condition_op: string; fi_condition_value: string;
  calc_field: string; calc_expression: string;
}

function configToFormState(type: RuleType, config: Record<string, unknown>): Partial<RuleConfigStateFull> {
  switch (type) {
    case 'set_value':
      return { sv_field: String(config.field ?? ''), sv_value: String(config.value ?? '') };
    case 'rename_field':
      return { rf_from: String(config.from_field ?? config.from ?? ''), rf_to: String(config.to_field ?? config.to ?? '') };
    case 'find_replace':
      return {
        fr_field: String(config.field ?? ''),
        fr_pattern: String(config.pattern ?? config.find ?? ''),
        fr_replacement: String(config.replacement ?? config.replace ?? ''),
        fr_use_regex: Boolean(config.use_regex ?? false),
      };
    case 'filter_include':
    case 'filter_exclude':
      return {
        fi_condition_field: String(config.condition_field ?? config.field ?? ''),
        fi_condition_op: String(config.condition_op ?? config.operator ?? 'eq'),
        fi_condition_value: String(config.condition_value ?? config.value ?? ''),
      };
    case 'calculated':
      return { calc_field: String(config.field ?? ''), calc_expression: String(config.expression ?? '') };
    default:
      return {};
  }
}

describe('configToFormState (NL reverse-mapping)', () => {
  it('maps set_value config → sv_field / sv_value', () => {
    const state = configToFormState('set_value', { field: 'brand', value: 'Acme' });
    expect(state.sv_field).toBe('brand');
    expect(state.sv_value).toBe('Acme');
  });

  it('maps rename_field config → rf_from / rf_to (from_field / to_field keys)', () => {
    const state = configToFormState('rename_field', { from_field: 'g:id', to_field: 'id' });
    expect(state.rf_from).toBe('g:id');
    expect(state.rf_to).toBe('id');
  });

  it('maps find_replace config → fr_* fields', () => {
    const state = configToFormState('find_replace', {
      field: 'title', pattern: 'foo', replacement: 'bar', use_regex: true,
    });
    expect(state.fr_field).toBe('title');
    expect(state.fr_pattern).toBe('foo');
    expect(state.fr_replacement).toBe('bar');
    expect(state.fr_use_regex).toBe(true);
  });

  it('maps filter_exclude config → fi_condition_* fields', () => {
    const state = configToFormState('filter_exclude', {
      condition_field: 'availability', condition_op: 'eq', condition_value: 'out of stock',
    });
    expect(state.fi_condition_field).toBe('availability');
    expect(state.fi_condition_op).toBe('eq');
    expect(state.fi_condition_value).toBe('out of stock');
  });

  it('maps filter_include config → fi_condition_* fields', () => {
    const state = configToFormState('filter_include', {
      condition_field: 'price', condition_op: 'gt', condition_value: '0',
    });
    expect(state.fi_condition_field).toBe('price');
    expect(state.fi_condition_op).toBe('gt');
  });

  it('maps calculated config → calc_field / calc_expression', () => {
    const state = configToFormState('calculated', { field: 'sale_price', expression: '{price} * 0.9' });
    expect(state.calc_field).toBe('sale_price');
    expect(state.calc_expression).toBe('{price} * 0.9');
  });

  it('falls back to alternate backend keys for rename_field (from/to)', () => {
    const state = configToFormState('rename_field', { from: 'old', to: 'new' });
    expect(state.rf_from).toBe('old');
    expect(state.rf_to).toBe('new');
  });
});

// ---------------------------------------------------------------------------
// FeedQualityResponse type contract
// ---------------------------------------------------------------------------

describe('FeedQualityResponse type', () => {
  it('carries score, total, valid, sampled, and issues', () => {
    const resp: FeedQualityResponse = {
      score: 85,
      total: 1000,
      valid: 950,
      sampled: false,
      issues: [
        {
          code: 'missing_recommended_field',
          severity: 'warning',
          field: 'description',
          message: 'Açıklama alanı eksik',
          affected_count: 50,
          sample_ids: ['id1', 'id2'],
        },
      ],
    };
    expect(resp.score).toBe(85);
    expect(resp.total).toBe(1000);
    expect(resp.valid).toBe(950);
    expect(resp.issues).toHaveLength(1);
    expect(resp.issues[0].severity).toBe('warning');
  });

  it('sampled is optional and may be omitted', () => {
    const resp: FeedQualityResponse = {
      score: 42,
      total: 200,
      valid: 84,
      issues: [],
    };
    expect(resp.sampled).toBeUndefined();
    expect(resp.issues).toHaveLength(0);
  });

  it('QualityIssue carries all six known codes', () => {
    const codes = [
      'missing_required_field',
      'missing_recommended_field',
      'duplicate_id',
      'invalid_price',
      'title_too_long',
      'missing_image',
    ];
    for (const code of codes) {
      const issue: QualityIssue = {
        code,
        severity: 'error',
        field: 'test_field',
        message: 'Test mesajı',
        affected_count: 1,
        sample_ids: [],
      };
      expect(issue.code).toBe(code);
    }
  });
});

// ---------------------------------------------------------------------------
// getChannelQuality — fetch mock
// ---------------------------------------------------------------------------

describe('getChannelQuality', () => {
  beforeEach(() => {
    if (typeof globalThis.localStorage === 'undefined') {
      Object.defineProperty(globalThis, 'localStorage', {
        value: { getItem: () => 'test-token', removeItem: vi.fn(), setItem: vi.fn() },
        writable: true,
      });
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('calls GET /api/v1/feeds/channels/{channelId}/quality and returns parsed response', async () => {
    const mockResponse: FeedQualityResponse = {
      score: 74,
      total: 500,
      valid: 370,
      sampled: true,
      issues: [
        {
          code: 'missing_required_field',
          severity: 'error',
          field: 'g:id',
          message: 'Zorunlu alan eksik: g:id',
          affected_count: 80,
          sample_ids: ['prod-001', 'prod-002'],
        },
        {
          code: 'invalid_price',
          severity: 'error',
          field: 'price',
          message: 'Geçersiz fiyat değeri',
          affected_count: 50,
          sample_ids: ['prod-010'],
        },
      ],
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getChannelQuality } = await import('@/lib/feeds-api');
    const result = await getChannelQuality('channel-abc');

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/feeds/channels/channel-abc/quality');
    // quality endpoint is GET — no method override
    expect((options?.method ?? 'GET').toUpperCase()).toBe('GET');
    expect(result.score).toBe(74);
    expect(result.total).toBe(500);
    expect(result.valid).toBe(370);
    expect(result.sampled).toBe(true);
    expect(result.issues).toHaveLength(2);
    expect(result.issues[0].code).toBe('missing_required_field');
    expect(result.issues[1].code).toBe('invalid_price');
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: () => Promise.resolve('Servis kullanılamıyor'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getChannelQuality: gq } = await import('@/lib/feeds-api');
    await expect(gq('channel-abc')).rejects.toThrow('Servis kullanılamıyor');
  });

  it('redirects to /login on 401', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve('Unauthorized'),
    });
    vi.stubGlobal('fetch', fetchMock);

    // Stub window.location so the redirect does not crash in test env
    const locationStub = { href: '' };
    Object.defineProperty(globalThis, 'window', {
      value: { location: locationStub, localStorage: globalThis.localStorage },
      writable: true,
    });

    const { getChannelQuality: gq } = await import('@/lib/feeds-api');
    await expect(gq('channel-xyz')).rejects.toThrow('Oturum süresi doldu');
  });
});

// ---------------------------------------------------------------------------
// EnrichmentSuggestion / EnrichSourceResponse type contracts
// ---------------------------------------------------------------------------

describe('EnrichSourceResponse type', () => {
  it('carries suggestions array with all expected fields', () => {
    const suggestion: EnrichmentSuggestion = {
      product_id: 'prod-001',
      field: 'color',
      current: null,
      suggested: 'Kırmızı',
      confidence: 'high',
      source: 'ai',
    };
    const resp: EnrichSourceResponse = {
      suggestions: [suggestion],
      sampled: false,
      sampled_total: null,
    };
    expect(resp.suggestions).toHaveLength(1);
    expect(resp.suggestions[0].field).toBe('color');
    expect(resp.suggestions[0].confidence).toBe('high');
    expect(resp.suggestions[0].source).toBe('ai');
    expect(resp.sampled).toBe(false);
    expect(resp.sampled_total).toBeNull();
  });

  it('accepts sampled=true with sampled_total', () => {
    const resp: EnrichSourceResponse = {
      suggestions: [],
      sampled: true,
      sampled_total: 10000,
    };
    expect(resp.sampled).toBe(true);
    expect(resp.sampled_total).toBe(10000);
  });

  it('accepts heuristic source with low confidence', () => {
    const s: EnrichmentSuggestion = {
      product_id: 'prod-002',
      field: 'brand',
      current: '',
      suggested: 'Acme',
      confidence: 'low',
      source: 'heuristic',
    };
    expect(s.source).toBe('heuristic');
    expect(s.confidence).toBe('low');
  });

  it('covers all five enrichable fields as valid values', () => {
    const fields = ['color', 'brand', 'category', 'material', 'title'] as const;
    for (const field of fields) {
      const s: EnrichmentSuggestion = {
        product_id: 'x',
        field,
        current: null,
        suggested: 'Test',
        confidence: 'high',
        source: 'ai',
      };
      expect(s.field).toBe(field);
    }
  });
});

// ---------------------------------------------------------------------------
// ApplyEnrichmentResponse type contract
// ---------------------------------------------------------------------------

describe('ApplyEnrichmentResponse type', () => {
  it('carries applied_count', () => {
    const resp: ApplyEnrichmentResponse = { applied_count: 7 };
    expect(resp.applied_count).toBe(7);
  });
});

// ---------------------------------------------------------------------------
// enrichSource — fetch mock
// ---------------------------------------------------------------------------

describe('enrichSource', () => {
  beforeEach(() => {
    if (typeof globalThis.localStorage === 'undefined') {
      Object.defineProperty(globalThis, 'localStorage', {
        value: { getItem: () => 'test-token', removeItem: vi.fn(), setItem: vi.fn() },
        writable: true,
      });
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('calls POST /api/v1/feeds/sources/{sourceId}/enrich with correct body and returns parsed response', async () => {
    const mockResponse: EnrichSourceResponse = {
      suggestions: [
        {
          product_id: 'prod-abc',
          field: 'color',
          current: null,
          suggested: 'Mavi',
          confidence: 'high',
          source: 'ai',
        },
        {
          product_id: 'prod-def',
          field: 'brand',
          current: '',
          suggested: 'Acme',
          confidence: 'low',
          source: 'heuristic',
        },
      ],
      sampled: true,
      sampled_total: 5000,
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { enrichSource: es } = await import('@/lib/feeds-api');
    const result = await es('source-123', { fields: ['color', 'brand'] });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/feeds/sources/source-123/enrich');
    expect(options.method).toBe('POST');
    const body = JSON.parse(options.body as string);
    expect(body.fields).toEqual(['color', 'brand']);
    expect(result.suggestions).toHaveLength(2);
    expect(result.suggestions[0].product_id).toBe('prod-abc');
    expect(result.suggestions[0].confidence).toBe('high');
    expect(result.suggestions[1].confidence).toBe('low');
    expect(result.sampled).toBe(true);
    expect(result.sampled_total).toBe(5000);
  });

  it('passes optional product_ids and limit in request body', async () => {
    const mockResponse: EnrichSourceResponse = { suggestions: [], sampled: false, sampled_total: null };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve('{}'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { enrichSource: es } = await import('@/lib/feeds-api');
    await es('source-xyz', { fields: ['title'], product_ids: ['p1', 'p2'], limit: 50 });

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string);
    expect(body.product_ids).toEqual(['p1', 'p2']);
    expect(body.limit).toBe(50);
  });

  it('throws on non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: () => Promise.resolve('Geçersiz alanlar'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { enrichSource: es } = await import('@/lib/feeds-api');
    await expect(es('source-123', { fields: ['color'] })).rejects.toThrow('Geçersiz alanlar');
  });
});

// ---------------------------------------------------------------------------
// applyEnrichment — fetch mock
// ---------------------------------------------------------------------------

describe('applyEnrichment', () => {
  beforeEach(() => {
    if (typeof globalThis.localStorage === 'undefined') {
      Object.defineProperty(globalThis, 'localStorage', {
        value: { getItem: () => 'test-token', removeItem: vi.fn(), setItem: vi.fn() },
        writable: true,
      });
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('calls POST /api/v1/feeds/sources/{sourceId}/enrich/apply with approvals and returns applied_count', async () => {
    const mockResponse: ApplyEnrichmentResponse = { applied_count: 3 };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { applyEnrichment: ae } = await import('@/lib/feeds-api');
    const result = await ae('source-123', {
      approvals: [
        { product_id: 'prod-abc', field: 'color', value: 'Mavi' },
        { product_id: 'prod-def', field: 'brand', value: 'Acme' },
        { product_id: 'prod-ghi', field: 'title', value: 'Yeni Başlık' },
      ],
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/feeds/sources/source-123/enrich/apply');
    expect(options.method).toBe('POST');
    const body = JSON.parse(options.body as string);
    expect(body.approvals).toHaveLength(3);
    expect(body.approvals[0]).toEqual({ product_id: 'prod-abc', field: 'color', value: 'Mavi' });
    expect(result.applied_count).toBe(3);
  });

  it('sends empty approvals array when nothing is approved', async () => {
    const mockResponse: ApplyEnrichmentResponse = { applied_count: 0 };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { applyEnrichment: ae } = await import('@/lib/feeds-api');
    const result = await ae('source-xyz', { approvals: [] });

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string);
    expect(body.approvals).toEqual([]);
    expect(result.applied_count).toBe(0);
  });

  it('throws on non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      text: () => Promise.resolve('Onay verisi hatalı'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { applyEnrichment: ae } = await import('@/lib/feeds-api');
    await expect(ae('source-123', { approvals: [] })).rejects.toThrow('Onay verisi hatalı');
  });
});
