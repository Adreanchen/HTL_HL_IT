#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct {
  char name[16];
  void (*func)();
} obj;

void win() { puts("FLAG{4bhits_0wns_the_heap}"); }

void hello() { printf("Hello :) %p %p\n", &hello, &win); }

int main() {
  obj *o = malloc(sizeof(obj));
  o->func = hello;
  memcpy(o->name, "Adrian", 7);

  free(o);

  printf("Leaked base address: %p\n", &main);
  puts("Input:");
  read(0, o->name, 32);

  o->func();
  return 0;
}