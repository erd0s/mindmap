//go:build ignore

// generate_icon creates the complete macOS iconset from a small vector-like
// drawing. It uses only the Go standard library so release builds do not need
// an image tool beyond Apple's iconutil.
package main

import (
	"fmt"
	"image"
	"image/color"
	"image/png"
	"math"
	"os"
	"path/filepath"
)

type point struct{ x, y float64 }

var iconFiles = []struct {
	name string
	size int
}{
	{"icon_16x16.png", 16}, {"icon_16x16@2x.png", 32},
	{"icon_32x32.png", 32}, {"icon_32x32@2x.png", 64},
	{"icon_128x128.png", 128}, {"icon_128x128@2x.png", 256},
	{"icon_256x256.png", 256}, {"icon_256x256@2x.png", 512},
	{"icon_512x512.png", 512}, {"icon_512x512@2x.png", 1024},
}

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: go run generate_icon.go OUTPUT.iconset")
		os.Exit(2)
	}
	directory := os.Args[1]
	if err := os.MkdirAll(directory, 0o755); err != nil {
		panic(err)
	}
	for _, target := range iconFiles {
		if err := writeIcon(filepath.Join(directory, target.name), target.size); err != nil {
			panic(err)
		}
	}
}

func writeIcon(path string, size int) error {
	const samples = 2
	highSize := size * samples
	high := image.NewNRGBA(image.Rect(0, 0, highSize, highSize))
	for y := range highSize {
		for x := range highSize {
			unit := point{float64(x) / float64(highSize), float64(y) / float64(highSize)}
			high.SetNRGBA(x, y, pixel(unit, highSize))
		}
	}
	result := image.NewNRGBA(image.Rect(0, 0, size, size))
	for y := range size {
		for x := range size {
			var red, green, blue, alpha uint32
			for dy := range samples {
				for dx := range samples {
					value := high.NRGBAAt(x*samples+dx, y*samples+dy)
					red += uint32(value.R)
					green += uint32(value.G)
					blue += uint32(value.B)
					alpha += uint32(value.A)
				}
			}
			result.SetNRGBA(x, y, color.NRGBA{
				R: uint8(red / 4), G: uint8(green / 4), B: uint8(blue / 4), A: uint8(alpha / 4),
			})
		}
	}
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	if err := png.Encode(file, result); err != nil {
		file.Close()
		return err
	}
	return file.Close()
}

func pixel(value point, pixels int) color.NRGBA {
	backgroundAlpha := coverage(roundedBoxDistance(value, point{0.5, 0.5}, 0.84, 0.20), pixels)
	if backgroundAlpha == 0 {
		return color.NRGBA{}
	}
	shade := uint8(16 + 12*value.y)
	result := color.NRGBA{R: shade, G: shade, B: shade + 3, A: backgroundAlpha}
	root := point{0.31, 0.50}
	upper := point{0.68, 0.29}
	lower := point{0.68, 0.71}
	if lineCoverage(value, root, upper, 0.050, pixels) > 0 || lineCoverage(value, root, lower, 0.050, pixels) > 0 {
		result = blend(result, color.NRGBA{R: 82, G: 82, B: 91, A: 255})
	}
	result = paintCircle(result, value, root, 0.125, color.NRGBA{R: 251, G: 191, B: 36, A: 255}, pixels)
	result = paintCircle(result, value, upper, 0.105, color.NRGBA{R: 34, G: 211, B: 238, A: 255}, pixels)
	result = paintCircle(result, value, lower, 0.105, color.NRGBA{R: 139, G: 92, B: 246, A: 255}, pixels)
	return result
}

func paintCircle(base color.NRGBA, value, centre point, radius float64, fill color.NRGBA, pixels int) color.NRGBA {
	distance := math.Hypot(value.x-centre.x, value.y-centre.y) - radius
	fill.A = coverage(distance, pixels)
	return blend(base, fill)
}

func lineCoverage(value, start, end point, width float64, pixels int) uint8 {
	dx, dy := end.x-start.x, end.y-start.y
	lengthSquared := dx*dx + dy*dy
	t := ((value.x-start.x)*dx + (value.y-start.y)*dy) / lengthSquared
	t = math.Max(0, math.Min(1, t))
	distance := math.Hypot(value.x-(start.x+t*dx), value.y-(start.y+t*dy)) - width/2
	return coverage(distance, pixels)
}

func roundedBoxDistance(value, centre point, size, radius float64) float64 {
	x := math.Abs(value.x-centre.x) - (size/2 - radius)
	y := math.Abs(value.y-centre.y) - (size/2 - radius)
	outside := math.Hypot(math.Max(x, 0), math.Max(y, 0))
	inside := math.Min(math.Max(x, y), 0)
	return outside + inside - radius
}

func coverage(distance float64, pixels int) uint8 {
	value := 0.5 - distance*float64(pixels)
	value = math.Max(0, math.Min(1, value))
	return uint8(math.Round(value * 255))
}

func blend(bottom, top color.NRGBA) color.NRGBA {
	alpha := float64(top.A) / 255
	inverse := 1 - alpha
	return color.NRGBA{
		R: uint8(float64(top.R)*alpha + float64(bottom.R)*inverse),
		G: uint8(float64(top.G)*alpha + float64(bottom.G)*inverse),
		B: uint8(float64(top.B)*alpha + float64(bottom.B)*inverse),
		A: uint8(float64(top.A) + float64(bottom.A)*inverse),
	}
}
