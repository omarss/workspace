package net.omarss.omono.ui.places

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.Atm
import androidx.compose.material.icons.filled.BakeryDining
import androidx.compose.material.icons.filled.ContentCut
import androidx.compose.material.icons.filled.DirectionsBus
import androidx.compose.material.icons.filled.ElectricBolt
import androidx.compose.material.icons.filled.Fastfood
import androidx.compose.material.icons.filled.FitnessCenter
import androidx.compose.material.icons.filled.LocalCafe
import androidx.compose.material.icons.filled.LocalCarWash
import androidx.compose.material.icons.filled.LocalDrink
import androidx.compose.material.icons.filled.LocalGasStation
import androidx.compose.material.icons.filled.LocalHospital
import androidx.compose.material.icons.filled.LocalLaundryService
import androidx.compose.material.icons.filled.LocalLibrary
import androidx.compose.material.icons.filled.LocalMall
import androidx.compose.material.icons.filled.LocalPharmacy
import androidx.compose.material.icons.filled.LocalPostOffice
import androidx.compose.material.icons.filled.Mosque
import androidx.compose.material.icons.filled.Park
import androidx.compose.material.icons.filled.Restaurant
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import net.omarss.omono.feature.places.PlaceCategory

// Material-symbol icon + brand-ish accent colour for every place
// category. Kept at the UI layer (not on the enum itself) so the
// feature/places module stays free of compose-material-icons deps —
// the domain just knows the slug + label and the UI decides how to
// render it. Colours are eyeballed for legibility on both light and
// dark surfaces (all saturated enough to read at 14 % alpha background
// tints, dim enough to not glare on pure-white).
data class PlaceCategoryVisual(
    val icon: ImageVector,
    val tint: Color,
)

fun PlaceCategory.visual(): PlaceCategoryVisual = when (this) {
    PlaceCategory.COFFEE -> PlaceCategoryVisual(Icons.Filled.LocalCafe, Color(0xFF8B5E34))
    PlaceCategory.RESTAURANT -> PlaceCategoryVisual(Icons.Filled.Restaurant, Color(0xFFEF4444))
    PlaceCategory.FAST_FOOD -> PlaceCategoryVisual(Icons.Filled.Fastfood, Color(0xFFF97316))
    PlaceCategory.BAKERY -> PlaceCategoryVisual(Icons.Filled.BakeryDining, Color(0xFFCA8A04))
    PlaceCategory.GROCERY -> PlaceCategoryVisual(Icons.Filled.ShoppingCart, Color(0xFF22C55E))
    PlaceCategory.MALL -> PlaceCategoryVisual(Icons.Filled.LocalMall, Color(0xFFEC4899))
    PlaceCategory.FUEL -> PlaceCategoryVisual(Icons.Filled.LocalGasStation, Color(0xFF0EA5E9))
    PlaceCategory.EV_CHARGER -> PlaceCategoryVisual(Icons.Filled.ElectricBolt, Color(0xFF10B981))
    PlaceCategory.CAR_WASH -> PlaceCategoryVisual(Icons.Filled.LocalCarWash, Color(0xFF3B82F6))
    PlaceCategory.PHARMACY -> PlaceCategoryVisual(Icons.Filled.LocalPharmacy, Color(0xFF14B8A6))
    PlaceCategory.HOSPITAL -> PlaceCategoryVisual(Icons.Filled.LocalHospital, Color(0xFFDC2626))
    PlaceCategory.GYM -> PlaceCategoryVisual(Icons.Filled.FitnessCenter, Color(0xFF6366F1))
    PlaceCategory.PARK -> PlaceCategoryVisual(Icons.Filled.Park, Color(0xFF16A34A))
    PlaceCategory.BANK -> PlaceCategoryVisual(Icons.Filled.AccountBalance, Color(0xFF475569))
    PlaceCategory.ATM -> PlaceCategoryVisual(Icons.Filled.Atm, Color(0xFF64748B))
    PlaceCategory.MOSQUE -> PlaceCategoryVisual(Icons.Filled.Mosque, Color(0xFF059669))
    PlaceCategory.SALON -> PlaceCategoryVisual(Icons.Filled.ContentCut, Color(0xFFDB2777))
    PlaceCategory.LAUNDRY -> PlaceCategoryVisual(Icons.Filled.LocalLaundryService, Color(0xFF0284C7))
    PlaceCategory.POST_OFFICE -> PlaceCategoryVisual(Icons.Filled.LocalPostOffice, Color(0xFF2563EB))
    PlaceCategory.LIBRARY -> PlaceCategoryVisual(Icons.Filled.LocalLibrary, Color(0xFF7C3AED))
    PlaceCategory.TRANSIT -> PlaceCategoryVisual(Icons.Filled.DirectionsBus, Color(0xFFF59E0B))
    PlaceCategory.JUICE -> PlaceCategoryVisual(Icons.Filled.LocalDrink, Color(0xFFF43F5E))
}
