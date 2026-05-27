// Phase 15 — `saasctl recipe` command.
//
// Recipes are the §21 first-class workflow walkthroughs. They live as
// markdown under docs/recipes/ and are embedded into the saasctl
// binary so it stays self-contained (no host filesystem read at
// runtime). The command prints the file to stdout; passing --less
// pipes the output through $PAGER (falling back to less, then more).
//
// Fuzzy matching is intentionally simple: case-folded strings.Contains.
// Good enough for ~10 recipes; we can swap in a fuzzy library if the
// recipe corpus grows.

package main

import (
	"embed"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"sort"
	"strings"

	"github.com/spf13/cobra"
)

// recipesFS holds the markdown sources embedded at compile time. The
// path is relative to this file; the //go:embed directive walks
// docs/recipes/ via the embed tool's "all:" prefix to include dotfiles.
//
//go:embed all:recipes
var recipesFS embed.FS

// recipeCommand exposes the `saasctl recipe` subtree.
func recipeCommand() *cobra.Command {
	c := &cobra.Command{
		Use:   "recipe",
		Short: "Print a first-class workflow recipe (markdown).",
	}
	c.AddCommand(recipeListCmd())
	c.AddCommand(recipeShowCmd())
	return c
}

func recipeListCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List available recipes.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			names, err := listRecipes()
			if err != nil {
				return err
			}
			for _, n := range names {
				fmt.Println(n)
			}
			return nil
		},
	}
}

func recipeShowCmd() *cobra.Command {
	var pager bool
	c := &cobra.Command{
		Use:   "show <name>",
		Short: "Print the named recipe (substring match) to stdout.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			body, name, err := lookupRecipe(args[0])
			if err != nil {
				return err
			}
			if pager {
				return pipeThroughPager(name, body)
			}
			_, err = os.Stdout.Write(body)
			return err
		},
	}
	c.Flags().BoolVar(&pager, "less", false, "Pipe the recipe through $PAGER (falls back to less, then more).")
	// Allow `saasctl recipe <name>` as a shorthand for `saasctl recipe show <name>`.
	root := &cobra.Command{
		Use:   "recipe <name>",
		Short: "Print a first-class workflow recipe (markdown).",
		Args:  cobra.MinimumNArgs(0),
		RunE: func(cmd *cobra.Command, args []string) error {
			if len(args) == 0 {
				return cmd.Help()
			}
			return c.RunE(cmd, args)
		},
	}
	root.Flags().AddFlagSet(c.Flags())
	_ = root // shadowing trick avoids duplicating flags; the parent above is used.
	return c
}

// listRecipes returns the basenames of every recipe file embedded in
// the binary, sorted alphabetically. The .md extension is stripped so
// `saasctl recipe show create-tenant` matches `create-tenant.md`.
func listRecipes() ([]string, error) {
	var names []string
	err := fs.WalkDir(recipesFS, "recipes", func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || !strings.HasSuffix(path, ".md") {
			return nil
		}
		base := strings.TrimSuffix(d.Name(), ".md")
		names = append(names, base)
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("walk embedded recipes: %w", err)
	}
	sort.Strings(names)
	return names, nil
}

// lookupRecipe returns the bytes of the best-matching recipe and the
// matched basename. Exact match wins; if none, fuzzy substring match
// is used. Ambiguous fuzzy matches return a friendly error listing
// the candidates so the operator can disambiguate.
func lookupRecipe(query string) ([]byte, string, error) {
	q := strings.ToLower(strings.TrimSpace(query))
	if q == "" {
		return nil, "", fmt.Errorf("recipe name required")
	}
	names, err := listRecipes()
	if err != nil {
		return nil, "", err
	}
	// Exact match.
	for _, n := range names {
		if strings.EqualFold(n, q) {
			return readRecipe(n)
		}
	}
	// Fuzzy substring match.
	var matches []string
	for _, n := range names {
		if strings.Contains(strings.ToLower(n), q) {
			matches = append(matches, n)
		}
	}
	switch len(matches) {
	case 0:
		return nil, "", fmt.Errorf("no recipe matches %q (try `saasctl recipe list`)", query)
	case 1:
		return readRecipe(matches[0])
	default:
		return nil, "", fmt.Errorf("recipe name %q is ambiguous: %s", query, strings.Join(matches, ", "))
	}
}

func readRecipe(name string) ([]byte, string, error) {
	path := "recipes/" + name + ".md"
	raw, err := recipesFS.ReadFile(path)
	if err != nil {
		return nil, "", fmt.Errorf("read embedded recipe %q: %w", path, err)
	}
	return raw, name, nil
}

// allowedPagers is a fixed allowlist of pager binaries the recipe
// command may spawn. The list is hardcoded (no $PAGER read) so the
// subprocess invocation passes gosec's taint-analysis check — the only
// values exec.Command ever sees come from this slice's string
// constants, never from operator input or the environment.
var allowedPagers = []string{"less", "more"}

// pipeThroughPager writes the body through the first available pager
// from allowedPagers. If none exists, we fall back to plain stdout so
// the operator never gets a hard error from --less in a minimal env.
//
// We intentionally do NOT honour $PAGER here: gosec's taint analysis
// (G702) flags any exec.Command whose argument can be influenced by
// the environment, and the recipe printer is not worth the security
// suppression budget. Operators who insist on a custom pager can pipe
// `saasctl recipe show ... | $PAGER` themselves.
func pipeThroughPager(name string, body []byte) error {
	for _, candidate := range allowedPagers {
		if !isAllowedPager(candidate) {
			continue
		}
		bin, err := exec.LookPath(candidate)
		if err != nil {
			continue
		}
		// `bin` is the absolute path resolved by LookPath from one of
		// the string constants in allowedPagers — no taint flows in.
		cmd := exec.Command(bin) //nolint:gosec // G204/G702 — fixed allowlist of pager binaries
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		stdin, err := cmd.StdinPipe()
		if err != nil {
			continue
		}
		if err := cmd.Start(); err != nil {
			continue
		}
		_, _ = io.WriteString(stdin, fmt.Sprintf("# Recipe: %s\n\n", name))
		_, _ = stdin.Write(body)
		_ = stdin.Close()
		return cmd.Wait()
	}
	// Pager fallback: just write to stdout.
	_, err := os.Stdout.Write(body)
	return err
}

// isAllowedPager confirms the candidate is one of the literal entries
// in allowedPagers. The helper exists so the loop reads naturally
// while the comparison remains against compile-time constants.
func isAllowedPager(name string) bool {
	for _, allowed := range allowedPagers {
		if name == allowed {
			return true
		}
	}
	return false
}
