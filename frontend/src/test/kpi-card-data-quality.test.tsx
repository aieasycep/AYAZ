import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import KpiCard from '@/components/KpiCard';

describe('KpiCard — dataQuality prop', () => {
  it('renders neither warn dot nor stale clock when dataQuality is undefined (default)', () => {
    render(<KpiCard label="ROAS" value="2.4x" />);
    // No role="img" trust-signal elements should be present
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('renders neither warn dot nor stale clock when dataQuality is "ok"', () => {
    render(<KpiCard label="ROAS" value="2.4x" dataQuality="ok" />);
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('does not change the label or value for ok state', () => {
    render(<KpiCard label="Harcama" value="₺12.500" dataQuality="ok" />);
    expect(screen.getByText('Harcama')).toBeInTheDocument();
    expect(screen.getByText('₺12.500')).toBeInTheDocument();
  });

  it('renders an amber warn indicator with correct aria-label when dataQuality is "warn"', () => {
    render(<KpiCard label="ROAS" value="2.4x" dataQuality="warn" />);
    const indicator = screen.getByRole('img', { name: 'Veri kalitesi uyarısı' });
    expect(indicator).toBeInTheDocument();
  });

  it('warn indicator has tooltip title text', () => {
    render(<KpiCard label="ROAS" value="2.4x" dataQuality="warn" />);
    const indicator = screen.getByRole('img', { name: 'Veri kalitesi uyarısı' });
    expect(indicator).toHaveAttribute('title', "Veri kalitesi uyarısı — Hesap Taraması'na bakın");
  });

  it('renders a stale clock indicator with correct aria-label when dataQuality is "stale"', () => {
    render(<KpiCard label="ROAS" value="2.4x" dataQuality="stale" />);
    const indicator = screen.getByRole('img', { name: 'Veri güncel olmayabilir' });
    expect(indicator).toBeInTheDocument();
  });

  it('stale indicator has tooltip title text', () => {
    render(<KpiCard label="ROAS" value="2.4x" dataQuality="stale" />);
    const indicator = screen.getByRole('img', { name: 'Veri güncel olmayabilir' });
    expect(indicator).toHaveAttribute('title', 'Veri güncel olmayabilir');
  });

  it('warn and stale are mutually exclusive — warn renders warn indicator only', () => {
    render(<KpiCard label="CTR" value="3.2%" dataQuality="warn" />);
    expect(screen.getByRole('img', { name: 'Veri kalitesi uyarısı' })).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Veri güncel olmayabilir' })).toBeNull();
  });

  it('warn and stale are mutually exclusive — stale renders stale indicator only', () => {
    render(<KpiCard label="CTR" value="3.2%" dataQuality="stale" />);
    expect(screen.getByRole('img', { name: 'Veri güncel olmayabilir' })).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Veri kalitesi uyarısı' })).toBeNull();
  });

  it('existing props (delta, invertDelta, sub) still render correctly alongside dataQuality', () => {
    render(
      <KpiCard
        label="Harcama"
        value="₺10.000"
        sub="Toplam"
        delta={0.15}
        invertDelta
        dataQuality="stale"
      />,
    );
    expect(screen.getByText('Harcama')).toBeInTheDocument();
    expect(screen.getByText('₺10.000')).toBeInTheDocument();
    expect(screen.getByText('Toplam')).toBeInTheDocument();
    // delta badge should still be present
    expect(screen.getByText(/15,0/)).toBeInTheDocument();
    // stale indicator
    expect(screen.getByRole('img', { name: 'Veri güncel olmayabilir' })).toBeInTheDocument();
  });
});
