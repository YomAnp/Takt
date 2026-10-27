export function Flower({ small = false }: { small?: boolean }) {
  return (
    <svg
      className={small ? "flower small" : "flower"}
      viewBox="0 0 44 44"
      aria-hidden="true"
    >
      <path
        d="M22 21C8 28 4 15 12 9s15 1 10 12Zm1 1C16 8 29 4 35 12s-1 15-12 10Zm-1 1c14-7 18 6 10 12s-15-1-10-12Zm-1-1c7 14-6 18-12 10s1-15 12-10Z"
        fill="currentColor"
      />
      <circle cx="22" cy="22" r="4" fill="var(--paper)" />
    </svg>
  );
}
