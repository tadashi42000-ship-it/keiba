type Props = {
  values: number[];
  className?: string;
};

export function OddsSparkline({ values, className = "" }: Props) {
  const clean = values.filter((value) => Number.isFinite(value));
  if (clean.length < 3) return null;
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const range = max - min || 1;
  const width = 60;
  const height = 16;
  const points = clean
    .map((value, index) => {
      const x = clean.length === 1 ? 0 : (index / (clean.length - 1)) * width;
      const y = height - ((value - min) / range) * (height - 2) - 1;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className={`h-4 w-[60px] ${className}`} aria-hidden="true">
      <polyline points={points} stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
