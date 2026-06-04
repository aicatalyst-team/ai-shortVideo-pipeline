<script setup lang="ts">
import AppHeader from "@/components/layout/AppHeader.vue";
import AppSidebar from "@/components/layout/AppSidebar.vue";
import AppMain from "@/components/layout/AppMain.vue";
</script>

<template>
  <div class="min-h-screen flex flex-col">
    <AppHeader />
    <div class="flex flex-1 min-h-0">
      <AppSidebar />
      <AppMain>
        <router-view />
      </AppMain>
    </div>
  </div>
</template>
