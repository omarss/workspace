import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    GitHub({
      clientId: process.env.GITHUB_ID!,
      clientSecret: process.env.GITHUB_SECRET!,
    }),
  ],
  callbacks: {
    async jwt({ token, account, profile }) {
      // Persist GitHub ID and other profile data in the JWT
      if (account && profile) {
        token.github_id = profile.id;
        token.login = profile.login;
      }
      return token;
    },
    async session({ session, token }) {
      // Make GitHub data available in the session
      if (session.user) {
        (session.user as Record<string, unknown>).github_id = token.github_id;
        (session.user as Record<string, unknown>).login = token.login;
      }
      return session;
    },
  },
  pages: {
    signIn: "/",
  },
});
