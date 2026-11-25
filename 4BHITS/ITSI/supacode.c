#include <stdio.h>
unsigned int y = 0xcafebabe;
void *func(void) {
  unsigned int x = 0xaffed00d;
  printf("y=0x%X x=0x%X\n", y, x);
  return &x;
}
int main(void) {
  int *z;
  z = func();
  printf("0x%0X\n", *z);
  return 0;
}