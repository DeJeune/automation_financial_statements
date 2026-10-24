import { cleanup, effect, signal, View } from "nsh";
import { reduceMotion } from "nsh/accessibility";
import { Animated, type CompositeAnimation, createAnimatedValue, Easing } from "nsh/animated";
import { theme } from "./controls";

// This is a visual estimate. Only the real task ending can complete the sweep.
export function CardProgress(p: {
  category: string;
  identity: string;
  active: boolean;
  failed: boolean;
  delay: number;
}) {
  const visible = signal(false);
  const fill = createAnimatedValue(0.04);
  const fade = createAnimatedValue(0);
  let identity = "",
    active = false,
    generation = 0;
  let motion: CompositeAnimation | undefined;
  effect(() => {
    const nextIdentity = p.identity;
    const nextActive = p.active && !p.failed;
    const reduced = reduceMotion();
    if (identity !== nextIdentity) {
      identity = nextIdentity;
      generation++;
      motion?.stop();
      active = false;
      visible.set(false);
      fade.set(0);
      fill.set(0.04);
    }
    if (active === nextActive) return;
    active = nextActive;
    const run = ++generation;
    motion?.stop();
    if (active) {
      visible.set(true);
      fade.set(1);
      fill.set(reduced ? 1 : 0.04);
      if (reduced) return;
      motion = Animated.sequence([
        Animated.timing(fill, {
          toValue: 0.55,
          duration: 1800,
          delay: p.delay,
          easing: Easing.out(Easing.cubic),
        }),
        Animated.timing(fill, { toValue: 0.82, duration: 6500, easing: "easeOut" }),
        Animated.timing(fill, { toValue: 0.94, duration: 24000, easing: "easeOut" }),
      ]);
      void motion.start();
    } else if (p.failed || reduced) {
      fade.set(0);
      visible.set(false);
    } else {
      motion = Animated.sequence([
        Animated.timing(fill, { toValue: 1, duration: 260, easing: "easeOut" }),
        Animated.timing(fade, { toValue: 0, duration: 420, delay: 100 }),
      ]);
      void motion.start().then((finished) => {
        if (finished && generation === run) visible.set(false);
      });
    }
  });
  cleanup(() => {
    generation++;
    motion?.stop();
  });
  return (
    <If when={visible()}>
      <View
        testID={`card-progress-${p.category}`}
        pointerEvents="none"
        accessibilityElementsHidden
        style={{
          position: "absolute",
          top: 0,
          right: 0,
          bottom: 0,
          left: 0,
          borderRadius: 7,
          overflow: "hidden",
          opacity: fade,
        }}
      >
        <View
          style={{
            position: "absolute",
            top: 0,
            right: 0,
            bottom: 0,
            left: 0,
            transformOrigin: "left center",
            transform: [{ scaleX: fill }],
            backgroundImage:
              theme() === "dark"
                ? "linear-gradient(105deg, rgba(112, 205, 163, 0.05), rgba(112, 205, 163, 0.18) 85%, rgba(166, 235, 201, 0.26))"
                : "linear-gradient(105deg, rgba(60, 151, 108, 0.04), rgba(60, 151, 108, 0.14) 85%, rgba(92, 188, 142, 0.23))",
            animationName: p.active && !reduceMotion() ? "pulse" : "none",
            animationDuration: 2800,
            animationTimingFunction: "ease-in-out",
          }}
        />
      </View>
    </If>
  );
}
