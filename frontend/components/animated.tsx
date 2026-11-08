"use client";

import { motion, useMotionValue, useTransform, animate, AnimatePresence } from "framer-motion";
import { ReactNode, useEffect } from "react";
import clsx from "clsx";

/* ------------------------------------------------------------------ */
/* AnimatedNumber — smoothly tweens between numeric values             */
/* ------------------------------------------------------------------ */

export function AnimatedNumber({
  value, decimals = 2, prefix = "", suffix = "", className,
}: {
  value: number; decimals?: number; prefix?: string; suffix?: string; className?: string;
}) {
  const motionVal = useMotionValue(value);
  const rounded = useTransform(motionVal, (latest) =>
    `${prefix}${Number(latest).toFixed(decimals)}${suffix}`);
  useEffect(() => {
    const controls = animate(motionVal, value, { duration: 0.5, ease: "easeOut" });
    return controls.stop;
  }, [value, motionVal]);
  return <motion.span className={clsx("tabular", className)}>{rounded}</motion.span>;
}

/* ------------------------------------------------------------------ */
/* FadeInCard — staggered mount with subtle slide-up                   */
/* ------------------------------------------------------------------ */

export function FadeInCard({
  children, delay = 0, className,
}: { children: ReactNode; delay?: number; className?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay, ease: "easeOut" }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/* PulseBadge — pulsing background for critical states                 */
/* ------------------------------------------------------------------ */

export function PulseBadge({
  children, color = "red", className,
}: { children: ReactNode; color?: "red" | "amber" | "green" | "violet"; className?: string }) {
  const colorMap = {
    red:    "rgba(255, 59, 105, %)",
    amber:  "rgba(255, 176, 0, %)",
    green:  "rgba(0, 214, 143, %)",
    violet: "rgba(168, 85, 247, %)",
  };
  const base = colorMap[color];
  return (
    <motion.span
      animate={{
        boxShadow: [
          `0 0 0 0 ${base.replace("%", "0.5")}`,
          `0 0 0 8px ${base.replace("%", "0")}`,
          `0 0 0 0 ${base.replace("%", "0")}`,
        ],
      }}
      transition={{ duration: 1.8, repeat: Infinity, ease: "easeOut" }}
      className={clsx("inline-block px-1.5 py-0.5 rounded text-[10px] uppercase font-bold", className)}
    >
      {children}
    </motion.span>
  );
}

/* ------------------------------------------------------------------ */
/* GlowCard — wraps high-conviction signals with a halo                */
/* ------------------------------------------------------------------ */

export function GlowCard({
  children, intensity = "high", color = "amber", className,
}: {
  children: ReactNode;
  intensity?: "low" | "medium" | "high";
  color?: "amber" | "green" | "red" | "violet";
  className?: string;
}) {
  const blur = { low: 6, medium: 12, high: 24 }[intensity];
  const opacity = { low: 0.2, medium: 0.35, high: 0.55 }[intensity];
  const colorHex = { amber: "#d97706", green: "#00a86b", red: "#dc2626", violet: "#7c3aed" }[color];
  return (
    <motion.div
      animate={{
        boxShadow: [
          `0 0 ${blur}px ${Math.round(opacity * 255).toString(16)}00`,
          `0 0 ${blur * 1.5}px ${colorHex}${Math.round(opacity * 255).toString(16).padStart(2, "0")}`,
          `0 0 ${blur}px ${colorHex}${Math.round(opacity * 100).toString(16).padStart(2, "0")}`,
        ],
      }}
      transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
      className={clsx("rounded", className)}
    >
      {children}
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/* AnimatedList — children stagger in                                  */
/* ------------------------------------------------------------------ */

export function AnimatedList({ children, stagger = 0.05 }:
                              { children: ReactNode[]; stagger?: number }) {
  return (
    <AnimatePresence mode="popLayout">
      {children.map((c, i) => (
        <motion.div
          key={i}
          layout
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.3, delay: i * stagger }}
        >
          {c}
        </motion.div>
      ))}
    </AnimatePresence>
  );
}

/* ------------------------------------------------------------------ */
/* CountUpBadge — animated bullish/bearish change pill                 */
/* ------------------------------------------------------------------ */

export function ChangeBadge({ value, pct }: { value: number; pct: number }) {
  const up = value >= 0;
  return (
    <motion.span
      initial={{ scale: 0.9, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ duration: 0.25 }}
      className={clsx("tabular text-[10px]", up ? "text-accent-green" : "text-accent-red")}
    >
      {up ? "+" : ""}{value.toFixed(2)} ({up ? "+" : ""}{pct.toFixed(2)}%)
    </motion.span>
  );
}

/* ------------------------------------------------------------------ */
/* TickerScroll — marquee-style scrolling line                         */
/* ------------------------------------------------------------------ */

export function TickerScroll({ children }: { children: ReactNode }) {
  return (
    <motion.div
      animate={{ x: ["0%", "-50%"] }}
      transition={{ duration: 40, repeat: Infinity, ease: "linear" }}
      className="flex gap-6 whitespace-nowrap"
    >
      {children}
      {children}
    </motion.div>
  );
}
